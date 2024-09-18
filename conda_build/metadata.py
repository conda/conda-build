# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import time
import warnings
from collections import OrderedDict
from functools import lru_cache
from os.path import isdir, isfile, join
from typing import TYPE_CHECKING, NamedTuple, overload

import yaml
from bs4 import UnicodeDammit
from conda.base.context import locate_prefix_by_name
from conda.gateways.disk.read import compute_sum
from conda.models.match_spec import MatchSpec
from frozendict import deepfreeze

from . import utils
from .config import Config, get_or_merge_config
from .exceptions import (
    CondaBuildException,
    CondaBuildUserError,
    DependencyNeedsBuildingError,
    RecipeError,
    UnableToParse,
    UnableToParseMissingJinja2,
)
from .features import feature_list
from .license_family import ensure_valid_license_family
from .utils import (
    DEFAULT_SUBDIRS,
    ensure_list,
    expand_globs,
    find_recipe,
    get_installed_packages,
    insert_variant_versions,
    on_win,
)
from .variants import (
    dict_of_lists_to_list_of_dicts,
    find_used_variables_in_batch_script,
    find_used_variables_in_shell_script,
    find_used_variables_in_text,
    get_default_variant,
    get_vars,
    list_of_dicts_to_dict_of_lists,
)

if TYPE_CHECKING:
    from typing import Any, Literal, Self

    OutputDict = dict[str, Any]
    OutputTuple = tuple[OutputDict, "MetaData"]

try:
    import yaml
except ImportError:
    sys.exit(
        "Error: could not import yaml (required to read meta.yaml "
        "files of conda recipes)"
    )

try:
    Loader = yaml.CLoader
except AttributeError:
    Loader = yaml.Loader


class StringifyNumbersLoader(Loader):
    @classmethod
    def remove_implicit_resolver(cls, tag):
        if "yaml_implicit_resolvers" not in cls.__dict__:
            cls.yaml_implicit_resolvers = {
                k: v[:] for k, v in cls.yaml_implicit_resolvers.items()
            }
        for ch in tuple(cls.yaml_implicit_resolvers):
            resolvers = [(t, r) for t, r in cls.yaml_implicit_resolvers[ch] if t != tag]
            if resolvers:
                cls.yaml_implicit_resolvers[ch] = resolvers
            else:
                del cls.yaml_implicit_resolvers[ch]

    @classmethod
    def remove_constructor(cls, tag):
        if "yaml_constructors" not in cls.__dict__:
            cls.yaml_constructors = cls.yaml_constructors.copy()
        if tag in cls.yaml_constructors:
            del cls.yaml_constructors[tag]


StringifyNumbersLoader.remove_implicit_resolver("tag:yaml.org,2002:float")
StringifyNumbersLoader.remove_implicit_resolver("tag:yaml.org,2002:int")
StringifyNumbersLoader.remove_constructor("tag:yaml.org,2002:float")
StringifyNumbersLoader.remove_constructor("tag:yaml.org,2002:int")

# arches that don't follow exact names in the subdir need to be mapped here
ARCH_MAP = {"32": "x86", "64": "x86_64"}

NOARCH_TYPES = ("python", "generic", True)

# we originally matched outputs based on output name. Unfortunately, that
#    doesn't work when outputs are templated - we want to match un-rendered
#    text, but we have rendered names.
# We overcome that divide by finding the output index in a rendered set of
#    outputs, so our names match, then we use that numeric index with this
#    regex, which extract all outputs in order.
# Stop condition is one of 3 things:
#    \w at the start of a line (next top-level section)
#    \Z (end of file)
#    next output, as delineated by "- name" or "- type"
output_re = re.compile(
    r"^\ +-\ +(?:name|type):.+?(?=^\w|\Z|^\ +-\ +(?:name|type))", flags=re.M | re.S
)
numpy_xx_re = re.compile(
    r"(numpy\s*x\.x)|pin_compatible\([\'\"]numpy.*max_pin=[\'\"]x\.x[\'\"]"
)
# TODO: there's probably a way to combine these, but I can't figure out how to many the x
#     capturing group optional.
numpy_compatible_x_re = re.compile(
    r"pin_\w+\([\'\"]numpy[\'\"].*((?<=x_pin=[\'\"])[x\.]*(?=[\'\"]))"
)
numpy_compatible_re = re.compile(r"pin_\w+\([\'\"]numpy[\'\"]")

# used to avoid recomputing/rescanning recipe contents for used variables
used_vars_cache = {}


def get_selectors(config: Config) -> dict[str, bool]:
    """Aggregates selectors for use in recipe templating.

    Derives selectors from the config and variants to be injected
    into the Jinja environment prior to templating.

    Args:
        config (Config): The config object

    Returns:
        dict[str, bool]: Dictionary of on/off selectors for Jinja
    """
    # Remember to update the docs of any of this changes
    plat = config.host_subdir
    d = dict(
        linux32=bool(plat == "linux-32"),
        linux64=bool(plat == "linux-64"),
        arm=plat.startswith("linux-arm"),
        unix=plat.startswith(("linux-", "osx-", "emscripten-")),
        win32=bool(plat == "win-32"),
        win64=bool(plat == "win-64"),
        os=os,
        environ=os.environ,
        nomkl=bool(int(os.environ.get("FEATURE_NOMKL", False))),
    )

    # Add the current platform to the list of subdirs to enable conda-build
    # to bootstrap new platforms without a new conda release.
    subdirs = list(DEFAULT_SUBDIRS) + [plat]

    # filter out noarch and other weird subdirs
    subdirs = [subdir for subdir in subdirs if "-" in subdir]

    subdir_oses = {subdir.split("-")[0] for subdir in subdirs}
    subdir_archs = {subdir.split("-")[1] for subdir in subdirs}

    for subdir_os in subdir_oses:
        d[subdir_os] = plat.startswith(f"{subdir_os}-")

    for arch in subdir_archs:
        arch_full = ARCH_MAP.get(arch, arch)
        d[arch_full] = plat.endswith(f"-{arch}")
        if arch == "32":
            d["x86"] = plat.endswith(("-32", "-64"))

    defaults = get_default_variant(config)
    py = config.variant.get("python", defaults["python"])
    # there are times when python comes in as a tuple
    if not hasattr(py, "split"):
        py = py[0]
    # go from "3.6 *_cython" -> "36"
    # or from "3.6.9" -> "36"
    py_major, py_minor, *_ = py.split(" ")[0].split(".")
    py = int(f"{py_major}{py_minor}")

    d["build_platform"] = config.build_subdir

    d.update(
        dict(
            py=py,
            py3k=bool(py_major == "3"),
            py2k=bool(py_major == "2"),
            py26=bool(py == 26),
            py27=bool(py == 27),
            py33=bool(py == 33),
            py34=bool(py == 34),
            py35=bool(py == 35),
            py36=bool(py == 36),
        )
    )

    np = config.variant.get("numpy")
    if not np:
        np = defaults["numpy"]
        if config.verbose:
            utils.get_logger(__name__).warning(
                "No numpy version specified in conda_build_config.yaml.  "
                "Falling back to default numpy value of {}".format(defaults["numpy"])
            )
    d["np"] = int("".join(np.split(".")[:2]))

    pl = config.variant.get("perl", defaults["perl"])
    d["pl"] = pl

    lua = config.variant.get("lua", defaults["lua"])
    d["lua"] = lua
    d["luajit"] = bool(lua[0] == "2")

    for feature, value in feature_list:
        d[feature] = value
    d.update(os.environ)

    # here we try to do some type conversion for more intuitive usage.  Otherwise,
    #    values like 35 are strings by default, making relational operations confusing.
    # We also convert "True" and things like that to booleans.
    for k, v in config.variant.items():
        if k not in d:
            try:
                d[k] = int(v)
            except (TypeError, ValueError):
                if isinstance(v, str) and v.lower() in ("false", "true"):
                    v = v.lower() == "true"
                d[k] = v
    return d


def ns_cfg(config: Config) -> dict[str, bool]:
    warnings.warn(
        "`conda_build.metadata.ns_cfg` is pending deprecation and will be removed in a "
        "future release. Please use `conda_build.metadata.get_selectors` instead.",
        PendingDeprecationWarning,
    )
    return get_selectors(config)


# Selectors must be either:
# - at end of the line
# - embedded (anywhere) within a comment
#
# Notes:
# - [([^\[\]]+)\] means "find a pair of brackets containing any
#                 NON-bracket chars, and capture the contents"
# - (?(2)[^\(\)]*)$ means "allow trailing characters iff group 2 (#.*) was found."
#                 Skip markdown link syntax.
sel_pat = re.compile(r"(.+?)\s*(#.*)?\[([^\[\]]+)\](?(2)[^\(\)]*)$")


# this function extracts the variable name from a NameError exception, it has the form of:
# "NameError: name 'var' is not defined", where var is the variable that is not defined. This gets
#    returned
def parseNameNotFound(error):
    m = re.search("'(.+?)'", str(error))
    if len(m.groups()) == 1:
        return m.group(1)
    else:
        return ""


# We evaluate the selector and return True (keep this line) or False (drop this line)
# If we encounter a NameError (unknown variable in selector), then we replace it by False and
#     re-run the evaluation
def eval_selector(selector_string, namespace, variants_in_place):
    try:
        # TODO: is there a way to do this without eval?  Eval allows arbitrary
        #    code execution.
        return eval(selector_string, namespace, {})
    except NameError as e:
        missing_var = parseNameNotFound(e)
        if variants_in_place:
            log = utils.get_logger(__name__)
            log.debug(
                "Treating unknown selector '" + missing_var + "' as if it was False."
            )
        next_string = selector_string.replace(missing_var, "False")
        return eval_selector(next_string, namespace, variants_in_place)


@lru_cache(maxsize=None)
def _split_line_selector(text: str) -> tuple[tuple[str | None, str], ...]:
    lines: list[tuple[str | None, str]] = []
    for line in text.splitlines():
        line = line.rstrip()

        # skip comment lines, include a blank line as a placeholder
        if line.lstrip().startswith("#"):
            lines.append((None, ""))
            continue

        # include blank lines
        if not line:
            lines.append((None, ""))
            continue

        # user may have quoted entire line to make YAML happy
        trailing_quote = ""
        if line and line[-1] in ("'", '"'):
            trailing_quote = line[-1]

        # Checking for "[" and "]" before regex matching every line is a bit faster.
        if (
            ("[" in line and "]" in line)
            and (match := sel_pat.match(line))
            and (selector := match.group(3))
        ):
            # found a selector
            lines.append((selector, (match.group(1) + trailing_quote).rstrip()))
        else:
            # no selector found
            lines.append((None, line))
    return tuple(lines)


def select_lines(text: str, namespace: dict[str, Any], variants_in_place: bool) -> str:
    lines = []
    selector_cache: dict[str, bool] = {}
    for i, (selector, line) in enumerate(_split_line_selector(text)):
        if not selector:
            # no selector? include line as is
            lines.append(line)
        else:
            # include lines with a selector that evaluates to True
            try:
                if selector_cache[selector]:
                    lines.append(line)
            except KeyError:
                # KeyError: cache miss
                try:
                    value = bool(eval_selector(selector, namespace, variants_in_place))
                    selector_cache[selector] = value
                    if value:
                        lines.append(line)
                except Exception as e:
                    raise CondaBuildUserError(
                        f"Invalid selector in meta.yaml line {i + 1}:\n"
                        f"offending selector:\n"
                        f"  [{selector}]\n"
                        f"exception:\n"
                        f"  {e.__class__.__name__}: {e}\n"
                    )
    return "\n".join(lines) + "\n"


def yamlize(data):
    try:
        return yaml.load(data, Loader=StringifyNumbersLoader)
    except yaml.error.YAMLError as e:
        if "{{" in data:
            try:
                import jinja2

                jinja2  # Avoid pyflakes failure: 'jinja2' imported but unused
            except ImportError:
                raise UnableToParseMissingJinja2(original=e)
        print("Problematic recipe:", file=sys.stderr)
        print(data, file=sys.stderr)
        raise UnableToParse(original=e)


def ensure_valid_fields(meta):
    pin_depends = meta.get("build", {}).get("pin_depends", "")
    if pin_depends and pin_depends not in ("", "record", "strict"):
        raise RuntimeError(
            f"build/pin_depends must be 'record' or 'strict' - not '{pin_depends}'"
        )


def _trim_None_strings(meta_dict):
    log = utils.get_logger(__name__)
    for key, value in meta_dict.items():
        if hasattr(value, "keys"):
            meta_dict[key] = _trim_None_strings(value)
        elif value and hasattr(value, "__iter__") or isinstance(value, str):
            if isinstance(value, str):
                meta_dict[key] = None if "None" in value else value
            else:
                # support lists of dicts (homogeneous)
                keep = []
                if hasattr(next(iter(value)), "keys"):
                    for d in value:
                        trimmed_dict = _trim_None_strings(d)
                        if trimmed_dict:
                            keep.append(trimmed_dict)
                # support lists of strings (homogeneous)
                else:
                    keep = [i for i in value if i not in ("None", "NoneType")]
                meta_dict[key] = keep
        else:
            log.debug(
                f"found unrecognized data type in dictionary: {value}, type: {type(value)}"
            )
    return meta_dict


def ensure_valid_noarch_value(meta):
    build_noarch = meta.get("build", {}).get("noarch")
    if build_noarch and build_noarch not in NOARCH_TYPES:
        raise CondaBuildException(f"Invalid value for noarch: {build_noarch}")


def _get_all_dependencies(metadata, envs=("host", "build", "run")):
    reqs = []
    for _env in envs:
        reqs.extend(metadata.meta.get("requirements", {}).get(_env, []))
    return reqs


def _check_circular_dependencies(
    render_order: list[OutputTuple],
    config: Config | None = None,
) -> None:
    envs: tuple[str, ...]
    if config and config.host_subdir != config.build_subdir:
        # When cross compiling build dependencies are already built
        # and cannot come from the recipe as subpackages
        envs = ("host", "run")
    else:
        envs = ("build", "host", "run")

    pairs: list[tuple[str, str]] = []
    for idx, (_, metadata) in enumerate(render_order):
        name = metadata.name()
        for _, other_metadata in render_order[idx + 1 :]:
            other_name = other_metadata.name()
            if any(
                name == dep.split(" ")[0]
                for dep in _get_all_dependencies(other_metadata, envs=envs)
            ) and any(
                other_name == dep.split(" ")[0]
                for dep in _get_all_dependencies(metadata, envs=envs)
            ):
                pairs.append((name, other_name))

    if pairs:
        error = "Circular dependencies in recipe: \n"
        for pair in pairs:
            error += "    {} <-> {}\n".format(*pair)
        raise RecipeError(error)


def _check_run_constrained(metadata_tuples):
    errors = []
    for _, metadata in metadata_tuples:
        for dep in _get_all_dependencies(metadata, envs=("run_constrained",)):
            if "{{" in dep:
                # skip Jinja content; it might have not been rendered yet; we'll get it next call
                continue
            try:
                MatchSpec(dep)
            except ValueError as exc:
                errors.append(
                    f"- Output '{metadata.name()}' has invalid run_constrained item: {dep}. "
                    f"Reason: {exc}"
                )
    if errors:
        raise RecipeError("\n".join(["", *errors]))


def _variants_equal(metadata, output_metadata):
    match = True
    for key, val in metadata.config.variant.items():
        if (
            key in output_metadata.config.variant
            and val != output_metadata.config.variant[key]
        ):
            match = False
    return match


def ensure_matching_hashes(output_metadata):
    envs = "build", "host", "run"
    problemos = []
    for _, m in output_metadata.values():
        for _, om in output_metadata.values():
            if m != om:
                run_exports = om.get_value("build/run_exports", [])
                if hasattr(run_exports, "keys"):
                    run_exports_list = []
                    for export_type in utils.RUN_EXPORTS_TYPES:
                        run_exports_list = run_exports_list + run_exports.get(
                            export_type, []
                        )
                    run_exports = run_exports_list
                deps = _get_all_dependencies(om, envs) + run_exports
                for dep in deps:
                    if (
                        dep.startswith(m.name() + " ")
                        and len(dep.split(" ")) == 3
                        and dep.split(" ")[-1] != m.build_id()
                        and _variants_equal(m, om)
                    ):
                        problemos.append((m.name(), m.build_id(), dep, om.name()))

    if problemos:
        error = ""
        for prob in problemos:
            error += "Mismatching package: {} (id {}); dep: {}; consumer package: {}\n".format(
                *prob
            )
        raise RecipeError(
            "Mismatching hashes in recipe. Exact pins in dependencies "
            "that contribute to the hash often cause this. Can you "
            "change one or more exact pins to version bound constraints?\n"
            "Involved packages were:\n" + error
        )


def parse(data, config, path=None):
    data = select_lines(
        data,
        get_selectors(config),
        variants_in_place=bool(config.variant),
    )
    res = yamlize(data)
    # ensure the result is a dict
    if res is None:
        res = {}
    for field in FIELDS:
        if field not in res:
            continue
        # ensure that empty fields are dicts (otherwise selectors can cause invalid fields)
        if not res[field]:
            res[field] = {}
        # source field may be either a dictionary, or a list of dictionaries
        if field in OPTIONALLY_ITERABLE_FIELDS:
            if not (
                isinstance(res[field], dict)
                or (hasattr(res[field], "__iter__") and not isinstance(res[field], str))
            ):
                raise RuntimeError(
                    f"The {field} field should be a dict or list of dicts, not "
                    f"{res[field].__class__.__name__} in file {path}."
                )
        else:
            if not isinstance(res[field], dict):
                raise RuntimeError(
                    f"The {field} field should be a dict, not "
                    f"{res[field].__class__.__name__} in file {path}."
                )

    ensure_valid_fields(res)
    ensure_valid_license_family(res)
    ensure_valid_noarch_value(res)
    return sanitize(res)


TRUES = {"y", "on", "true", "yes"}
FALSES = {"n", "no", "false", "off"}

# If you update this please update the example in
# conda-docs/docs/source/build.rst
FIELDS = {
    "package": {
        "name": None,
        "version": str,
    },
    "source": {
        "fn": None,
        "url": None,
        "md5": str,
        "sha1": None,
        "sha256": None,
        "path": str,
        "path_via_symlink": None,
        "git_url": str,
        "git_tag": str,
        "git_branch": str,
        "git_rev": str,
        "git_depth": None,
        "hg_url": None,
        "hg_tag": None,
        "svn_url": str,
        "svn_rev": None,
        "svn_ignore_externals": None,
        "svn_username": None,
        "svn_password": None,
        "folder": None,
        "no_hoist": None,
        "patches": list,
    },
    "build": {
        "number": None,
        "string": str,
        "entry_points": list,
        "osx_is_app": bool,
        "disable_pip": None,
        "features": list,
        "track_features": list,
        "preserve_egg_dir": bool,
        "no_link": None,
        "binary_relocation": bool,
        "script": list,
        "noarch": str,
        "noarch_python": bool,
        "has_prefix_files": None,
        "binary_has_prefix_files": None,
        "ignore_prefix_files": None,
        "detect_binary_files_with_prefix": bool,
        "skip_compile_pyc": list,
        "rpaths": None,
        "rpaths_patcher": None,
        "script_env": list,
        "always_include_files": None,
        "skip": bool,
        "msvc_compiler": str,
        "pin_depends": str,  # still experimental
        "include_recipe": None,
        "preferred_env": str,
        "preferred_env_executable_paths": list,
        "run_exports": list,
        "ignore_run_exports": list,
        "ignore_run_exports_from": list,
        "requires_features": dict,
        "provides_features": dict,
        "force_use_keys": list,
        "force_ignore_keys": list,
        "merge_build_host": None,
        "pre-link": str,
        "post-link": str,
        "pre-unlink": str,
        "missing_dso_whitelist": None,
        "error_overdepending": None,
        "error_overlinking": None,
        "overlinking_ignore_patterns": [],
    },
    "outputs": {
        "name": None,
        "version": None,
        "number": None,
        "entry_points": None,
        "script": None,
        "script_interpreter": None,
        "build": None,
        "requirements": None,
        "test": None,
        "about": None,
        "extra": None,
        "files": None,
        "type": None,
        "run_exports": None,
        "target": None,
    },
    "requirements": {
        "build": list,
        "host": list,
        "run": list,
        "conflicts": list,
        "run_constrained": list,
    },
    "app": {
        "entry": None,
        "icon": None,
        "summary": None,
        "type": None,
        "cli_opts": None,
        "own_environment": bool,
    },
    "test": {
        "requires": list,
        "commands": list,
        "files": list,
        "imports": list,
        "source_files": list,
        "downstreams": list,
    },
    "about": {
        "home": None,
        # these are URLs
        "dev_url": None,
        "doc_url": None,
        "doc_source_url": None,
        "license_url": None,
        # text
        "license": None,
        "summary": None,
        "description": None,
        "license_family": None,
        # lists
        "identifiers": list,
        "tags": list,
        "keywords": list,
        # paths in source tree
        "license_file": None,
        "prelink_message": None,
        "readme": None,
    },
    "extra": {},
}

# Fields that may either be a dictionary or a list of dictionaries.
OPTIONALLY_ITERABLE_FIELDS = ("source", "outputs")


def sanitize(meta):
    """
    Sanitize the meta-data to remove aliases/handle deprecation
    """
    sanitize_funs = {
        "source": [_git_clean],
        "package": [_str_version],
        "build": [_str_version],
    }
    for section, funs in sanitize_funs.items():
        if section in meta:
            for func in funs:
                section_data = meta[section]
                # section is a dictionary
                if hasattr(section_data, "keys"):
                    section_data = func(section_data)
                # section is a list of dictionaries
                else:
                    section_data = [func(_d) for _d in section_data]
                meta[section] = section_data
    return meta


def _git_clean(source_meta):
    """
    Reduce the redundancy in git specification by removing git_tag and
    git_branch.

    If one is specified, copy to git_rev.

    If more than one field is used to specified, exit
    and complain.
    """
    git_rev_tags_old = ("git_branch", "git_tag")
    git_rev = "git_rev"

    git_rev_tags = (git_rev,) + git_rev_tags_old
    has_rev_tags = tuple(bool(source_meta.get(tag, "")) for tag in git_rev_tags)

    keys = [key for key in (git_rev, "git_branch", "git_tag") if key in source_meta]
    if not keys:
        # git_branch, git_tag, nor git_rev specified, return as-is
        return source_meta
    elif len(keys) > 1:
        raise CondaBuildUserError(f"Multiple git_revs: {', '.join(keys)}")

    # make a copy of the input so we have no side-effects
    ret_meta = source_meta.copy()
    # loop over the old versions
    for key, has in zip(git_rev_tags[1:], has_rev_tags[1:]):
        # update if needed
        if has:
            ret_meta[git_rev_tags[0]] = ret_meta[key]
        # and remove
        ret_meta.pop(key, None)

    return ret_meta


def _str_version(package_meta):
    if "version" in package_meta:
        package_meta["version"] = str(package_meta.get("version", ""))
    if "msvc_compiler" in package_meta:
        package_meta["msvc_compiler"] = str(package_meta.get("msvc_compiler", ""))
    return package_meta


def check_bad_chrs(value: str, field: str) -> None:
    bad_chrs = set("=@#$%^&*:;\"'\\|<>?/ ")
    if field in ("package/version", "build/string"):
        bad_chrs.add("-")
    if field != "package/version":
        bad_chrs.add("!")
    if invalid := bad_chrs.intersection(value):
        raise CondaBuildUserError(
            f"Bad character(s) ({''.join(sorted(invalid))}) in {field}: {value}."
        )


def get_package_version_pin(build_reqs, name):
    version = ""
    for spec in build_reqs:
        if spec.split()[0] == name and len(spec.split()) > 1:
            version = spec.split()[1]
    return version


def build_string_from_metadata(metadata):
    if metadata.meta.get("build", {}).get("string"):
        build_str = metadata.get_value("build/string")
    else:
        res = []
        build_or_host = "host" if metadata.is_cross else "build"
        build_pkg_names = [ms.name for ms in metadata.ms_depends(build_or_host)]
        build_deps = metadata.meta.get("requirements", {}).get(build_or_host, [])
        # TODO: this is the bit that puts in strings like py27np111 in the filename.  It would be
        #    nice to get rid of this, since the hash supercedes that functionally, but not clear
        #    whether anyone's tools depend on this file naming right now.
        for s, names, places in (
            ("np", "numpy", 2),
            ("py", "python", 2),
            ("pl", "perl", 3),
            ("lua", "lua", 2),
            ("r", ("r", "r-base"), 2),
            ("mro", "mro-base", 3),
            ("mro", "mro-base_impl", 3),
        ):
            for ms in metadata.ms_depends("run"):
                for name in ensure_list(names):
                    if ms.name == name and name in build_pkg_names:
                        # only append numpy when it is actually pinned
                        if name == "numpy" and not metadata.numpy_xx:
                            continue
                        if metadata.noarch == name or (
                            metadata.get_value("build/noarch_python")
                            and name == "python"
                        ):
                            res.append(s)
                        else:
                            pkg_names = list(ensure_list(names))
                            pkg_names.extend(
                                [
                                    _n.replace("-", "_")
                                    for _n in ensure_list(names)
                                    if "-" in _n
                                ]
                            )
                            for _n in pkg_names:
                                variant_version = get_package_version_pin(
                                    build_deps, _n
                                ) or metadata.config.variant.get(
                                    _n.replace("-", "_"), ""
                                )
                                if variant_version:
                                    break
                            entry = "".join([s] + variant_version.split(".")[:places])
                            if entry not in res:
                                res.append(entry)

        features = ensure_list(metadata.get_value("build/features", []))
        if res:
            res.append("_")
        if features:
            res.extend(("_".join(features), "_"))
        res.append(str(metadata.build_number()))
        build_str = "".join(res)
    return build_str


def _get_dependencies_from_environment(env_name_or_path):
    path = (
        env_name_or_path
        if isdir(env_name_or_path)
        else locate_prefix_by_name(env_name_or_path)
    )
    # construct build requirements that replicate the given bootstrap environment
    # and concatenate them to the build requirements from the recipe
    bootstrap_metadata = get_installed_packages(path)
    bootstrap_requirements = []
    for package, data in bootstrap_metadata.items():
        bootstrap_requirements.append(
            "{} {} {}".format(package, data["version"], data["build"])
        )
    return {"requirements": {"build": bootstrap_requirements}}


def _toposort_outputs(output_tuples: list[OutputTuple]) -> list[OutputTuple]:
    """This function is used to work out the order to run the install scripts
    for split packages based on any interdependencies. The result is just
    a re-ordering of outputs such that we can run them in that order and
    reset the initial set of files in the install prefix after each. This
    will naturally lead to non-overlapping files in each package and also
    the correct files being present during the install and test procedures,
    provided they are run in this order."""
    from conda.common.toposort import _toposort

    # We only care about the conda packages built by this recipe. Non-conda
    # packages get sorted to the end.
    conda_outputs: dict[str, list[OutputTuple]] = {}
    non_conda_outputs: list[OutputTuple] = []
    for output_tuple in output_tuples:
        output_d, _ = output_tuple
        if output_d.get("type", "conda").startswith("conda"):
            # conda packages must have a name
            # the same package name may be seen multiple times (variants)
            conda_outputs.setdefault(output_d["name"], []).append(output_tuple)
        elif "name" in output_d:
            non_conda_outputs.append(output_tuple)
        else:
            # TODO: is it even possible to get here? and if so should we silently ignore or error?
            utils.get_logger(__name__).warning(
                "Found an output without a name, skipping"
            )

    # Iterate over conda packages, creating a mapping of package names to their
    # dependencies to be used in toposort
    name_to_dependencies: dict[str, set[str]] = {}
    for name, same_name_outputs in conda_outputs.items():
        for output_d, output_metadata in same_name_outputs:
            # dependencies for all of the variants
            dependencies = (
                *output_metadata.get_value("requirements/run", []),
                *output_metadata.get_value("requirements/host", []),
                *(
                    output_metadata.get_value("requirements/build", [])
                    if not output_metadata.is_cross
                    else []
                ),
            )
            name_to_dependencies.setdefault(name, set()).update(
                dependency_name
                for dependency in dependencies
                if (dependency_name := dependency.split(" ")[0]) in conda_outputs
            )

    return [
        *(
            output
            for name in _toposort(name_to_dependencies)
            for output in conda_outputs[name]
        ),
        *non_conda_outputs,
    ]


def get_output_dicts_from_metadata(
    metadata: MetaData,
    outputs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    outputs = outputs or metadata.get_section("outputs")

    if not outputs:
        outputs = [{"name": metadata.name()}]
    else:
        assert not hasattr(outputs, "keys"), (
            "outputs specified as dictionary, but must be a "
            "list of dictionaries.  YAML syntax is: \n\n"
            "outputs:\n    - name: subpkg\n\n"
            "(note the - before the inner dictionary)"
        )
        # make a metapackage for the top-level package if the top-level requirements
        #     mention a subpackage,
        # but only if a matching output name is not explicitly provided
        if metadata.uses_subpackage and not any(
            metadata.name() == out.get("name", "") for out in outputs
        ):
            outputs.append(OrderedDict(name=metadata.name()))
    for out in outputs:
        if (
            out.get("name") == metadata.name()
            and "package:" in metadata.get_recipe_text()
        ):
            combine_top_level_metadata_with_output(metadata, out)
    return outputs


def finalize_outputs_pass(
    base_metadata,
    render_order,
    pass_no,
    outputs=None,
    permit_unsatisfiable_variants=False,
    bypass_env_check=False,
):
    from .render import finalize_metadata

    outputs = OrderedDict()
    # each of these outputs can have a different set of dependency versions from each other,
    #    but also from base_metadata
    for output_d, metadata in render_order.values():
        if metadata.skip():
            continue
        try:
            log = utils.get_logger(__name__)
            # We should reparse the top-level recipe to get all of our dependencies fixed up.
            # we base things on base_metadata because it has the record of the full origin recipe
            if base_metadata.config.verbose:
                log.info(f"Attempting to finalize metadata for {metadata.name()}")
            # Using base_metadata is important for keeping the reference to the parent recipe
            om = base_metadata.copy()
            # other_outputs is the context of what's available for
            # pin_subpackage. It's stored on the metadata object here, but not
            # on base_metadata, which om is a copy of. Before we do
            # re-rendering of om's metadata, we need to have other_outputs in
            # place, so it can refer to it for any pin_subpackage stuff it has.
            om.other_outputs = metadata.other_outputs
            om.config.variant = metadata.config.variant
            parent_metadata = om.copy()

            om.other_outputs.update(outputs)
            om.final = False
            # get the new output_d from the reparsed top-level metadata, so that we have any
            #    exact subpackage version/build string info
            output_d = om.get_rendered_output(metadata.name()) or {
                "name": metadata.name()
            }

            om = om.get_output_metadata(output_d)
            replacements = None
            if "replacements" in parent_metadata.config.variant:
                replacements = parent_metadata.config.variant["replacements"]
                del parent_metadata.config.variant["replacements"]
            parent_metadata.parse_until_resolved()
            if replacements:
                parent_metadata.config.variant["replacements"] = replacements

            if not bypass_env_check:
                fm = finalize_metadata(
                    om,
                    parent_metadata=parent_metadata,
                    permit_unsatisfiable_variants=permit_unsatisfiable_variants,
                )
            else:
                fm = om
            if not output_d.get("type") or output_d.get("type").startswith("conda"):
                outputs[
                    fm.name(),
                    deepfreeze({k: fm.config.variant[k] for k in fm.get_used_vars()}),
                ] = (output_d, fm)
        except DependencyNeedsBuildingError as e:
            if not permit_unsatisfiable_variants:
                raise
            else:
                log = utils.get_logger(__name__)
                log.warning(
                    "Could not finalize metadata due to missing dependencies: "
                    f"{e.packages}"
                )
                outputs[
                    metadata.name(),
                    deepfreeze(
                        {
                            k: metadata.config.variant[k]
                            for k in metadata.get_used_vars()
                        }
                    ),
                ] = (output_d, metadata)
    # in-place modification
    base_metadata.other_outputs = outputs
    base_metadata.final = False
    final_outputs = OrderedDict()
    for k, (out_d, m) in outputs.items():
        final_outputs[
            m.name(),
            deepfreeze({k: m.config.variant[k] for k in m.get_used_vars()}),
        ] = (out_d, m)
    return final_outputs


def get_updated_output_dict_from_reparsed_metadata(original_dict, new_outputs):
    output_d = original_dict
    if "name" in original_dict:
        output_ds = [
            out
            for out in new_outputs
            if "name" in out and out["name"] == original_dict["name"]
        ]
        assert len(output_ds) == 1
        output_d = output_ds[0]
    return output_d


@lru_cache(maxsize=200)
def _filter_recipe_text(text, extract_pattern=None):
    if extract_pattern:
        match = re.search(extract_pattern, text, flags=re.MULTILINE | re.DOTALL)
        text = (
            "\n".join({string for string in match.groups() if string}) if match else ""
        )
    return text


@lru_cache(maxsize=None)
def read_meta_file(meta_path):
    with open(meta_path, "rb") as f:
        recipe_text = UnicodeDammit(f.read()).unicode_markup
    if hasattr(recipe_text, "decode"):
        recipe_text = recipe_text.decode()
    return recipe_text


def combine_top_level_metadata_with_output(metadata, output):
    """Merge top-level metadata into output when output is same name as top-level"""
    sections = ("requirements", "build", "about")
    for section in sections:
        metadata_section = metadata.meta.get(section, {}) or {}
        output_section = output.get(section, {}) or {}
        if section == "requirements":
            output_section = utils.expand_reqs(output.get(section, {}))
        for k, v in metadata_section.items():
            if k not in output_section:
                output_section[k] = v
        output[section] = output_section
        # synchronize them
        metadata.meta[section] = output_section


def trim_build_only_deps(metadata, requirements_used):
    """things can be used as dependencies or elsewhere in the recipe.  If it's only used
    elsewhere, keep it. If it's a dep-related thing, only keep it if
    it's in the build deps."""

    # filter out things that occur only in run requirements.  These don't actually affect the
    #     outcome of the package.
    output_reqs = utils.expand_reqs(metadata.meta.get("requirements", {}))
    build_reqs = utils.ensure_list(output_reqs.get("build", []))
    host_reqs = utils.ensure_list(output_reqs.get("host", []))
    run_reqs = output_reqs.get("run", [])
    build_reqs = {req.split()[0].replace("-", "_") for req in build_reqs if req}
    host_reqs = {req.split()[0].replace("-", "_") for req in host_reqs if req}

    to_remove = set()
    ignore_build_only_deps = sorted(
        utils.ensure_list(metadata.config.variant.get("ignore_build_only_deps", []))
    )

    for dep in requirements_used:
        # filter out stuff that's only in run deps
        if dep in run_reqs:
            if (
                dep not in build_reqs
                and dep not in host_reqs
                and dep in requirements_used
            ):
                to_remove.add(dep)
        else:
            if (
                dep in build_reqs
                and dep not in host_reqs
                and dep in requirements_used
                and dep in ignore_build_only_deps
            ):
                to_remove.add(dep)

    return requirements_used - to_remove


def _hash_dependencies(hashing_dependencies, hash_length):
    hash_ = hashlib.sha1(json.dumps(hashing_dependencies, sort_keys=True).encode())
    # save only the first HASH_LENGTH characters - should be more than
    #    enough, since these only need to be unique within one version
    # plus one is for the h - zero pad on the front, trim to match HASH_LENGTH
    return f"h{hash_.hexdigest()}"[: hash_length + 1]


class MetaData:
    def __init__(self, path, config=None, variant=None):
        self.undefined_jinja_vars = []
        self.config = get_or_merge_config(config, variant=variant)

        if isfile(path):
            self._meta_path = path
            self._meta_name = os.path.basename(path)
            self.path = os.path.dirname(path)
        else:
            self._meta_path = find_recipe(path)
            self._meta_name = "meta.yaml"
            self.path = os.path.dirname(self.meta_path)
        self.requirements_path = join(self.path, "requirements.txt")

        # Start with bare-minimum contents so we can call environ.get_dict() with impunity
        # We'll immediately replace these contents in parse_again()
        self.meta = dict()

        # This is the 'first pass' parse of meta.yaml, so not all variables are defined yet
        # (e.g. GIT_FULL_HASH, etc. are undefined)
        # Therefore, undefined jinja variables are permitted here
        # In the second pass, we'll be more strict. See build.build()
        # Primarily for debugging.  Ensure that metadata is not altered after "finalizing"
        self.parse_again(permit_undefined_jinja=True, allow_no_other_outputs=True)
        self.config.disable_pip = self.disable_pip
        # establish whether this recipe should squish build and host together

    @property
    def is_cross(self) -> bool:
        return bool(
            self.get_depends_top_and_out("host")
            or "host" in self.get_section("requirements")
        )

    @property
    def final(self) -> bool:
        return bool(self.get_value("extra/final"))

    @final.setter
    def final(self, value: bool) -> None:
        self.meta.setdefault("extra", {})["final"] = bool(value)

    @property
    def disable_pip(self) -> bool:
        return bool(self.config.disable_pip or self.get_value("build/disable_pip"))

    @disable_pip.setter
    def disable_pip(self, value: bool) -> None:
        self.config.disable_pip = bool(value)
        self.meta.setdefault("build", {})["disable_pip"] = bool(value)

    def append_metadata_sections(
        self, sections_file_or_dict, merge, raise_on_clobber=False
    ):
        """Append to or replace subsections to meta.yaml

        This is used to alter input recipes, so that a given requirement or
        setting is applied without manually altering the input recipe. It is
        intended for vendors who want to extend existing recipes without
        necessarily removing information. pass merge=False to replace sections.
        """
        if hasattr(sections_file_or_dict, "keys"):
            build_config = sections_file_or_dict
        else:
            with open(sections_file_or_dict) as configfile:
                build_config = parse(configfile.read(), config=self.config)
        utils.merge_or_update_dict(
            self.meta,
            build_config,
            self.path,
            merge=merge,
            raise_on_clobber=raise_on_clobber,
        )

    @property
    def is_output(self) -> str:
        parent_name = self.get_value("extra/parent_recipe", {}).get("name")
        return parent_name and parent_name != self.name()

    def parse_again(
        self,
        permit_undefined_jinja=False,
        allow_no_other_outputs=False,
        bypass_env_check=False,
        **kw,
    ):
        """Redo parsing for key-value pairs that are not initialized in the
        first pass.

        config: a conda-build Config object.  If None, the config object passed at creation
                time is used.

        permit_undefined_jinja: If True, *any* use of undefined jinja variables will
                                evaluate to an emtpy string, without emitting an error.
        """
        assert not self.final, "modifying metadata after finalization"

        log = utils.get_logger(__name__)
        if kw:
            log.warning(
                "using unsupported internal conda-build function `parse_again`.  Please use "
                "conda_build.api.render instead."
            )

        append_sections_file = None
        clobber_sections_file = None
        # we sometimes create metadata from dictionaries, in which case we'll have no path
        if self.meta_path:
            self.meta = parse(
                self._get_contents(
                    permit_undefined_jinja,
                    allow_no_other_outputs=allow_no_other_outputs,
                    bypass_env_check=bypass_env_check,
                ),
                config=self.config,
                path=self.meta_path,
            )

            append_sections_file = os.path.join(self.path, "recipe_append.yaml")
            clobber_sections_file = os.path.join(self.path, "recipe_clobber.yaml")

        append_sections_file = self.config.append_sections_file or append_sections_file
        if append_sections_file and not os.path.isfile(append_sections_file):
            log.debug(
                "input append sections file did not exist: %s", append_sections_file
            )
            append_sections_file = None
        clobber_sections_file = (
            self.config.clobber_sections_file or clobber_sections_file
        )
        if clobber_sections_file and not os.path.isfile(clobber_sections_file):
            log.debug(
                "input clobber sections file did not exist: %s", clobber_sections_file
            )
            clobber_sections_file = None

        if append_sections_file:
            self.append_metadata_sections(append_sections_file, merge=True)
        if clobber_sections_file:
            self.append_metadata_sections(clobber_sections_file, merge=False)
        if self.config.bootstrap:
            dependencies = _get_dependencies_from_environment(self.config.bootstrap)
            self.append_metadata_sections(dependencies, merge=True)

        if "error_overlinking" in self.get_section("build"):
            self.config.error_overlinking = self.meta["build"]["error_overlinking"]
        if "error_overdepending" in self.get_section("build"):
            self.config.error_overdepending = self.meta["build"]["error_overdepending"]

        self.validate_features()
        self.ensure_no_pip_requirements()

    def ensure_no_pip_requirements(self):
        for key in ("requirements/build", "requirements/run", "test/requires"):
            if any(hasattr(item, "keys") for item in (self.get_value(key) or [])):
                raise ValueError(
                    "Dictionaries are not supported as values in requirements sections"
                    ".  Note that pip requirements as used in conda-env "
                    "environment.yml files are not supported by conda-build."
                )

    def append_requirements(self):
        """For dynamic determination of build or run reqs, based on configuration"""
        run_reqs = self.meta.setdefault("requirements", {}).setdefault("run", [])
        if (
            self.get_value("build/osx_is_app", False)
            and self.config.platform == "osx"
            and "python.app" not in run_reqs
        ):
            run_reqs.append("python.app")

    def parse_until_resolved(
        self, allow_no_other_outputs=False, bypass_env_check=False
    ):
        """variant contains key-value mapping for additional functions and values
        for jinja2 variables"""
        # store the "final" state that we think we're in.  reloading the meta.yaml file
        #   can reset it (to True)
        final = self.final

        # always parse again at least once
        self.parse_again(
            permit_undefined_jinja=True,
            allow_no_other_outputs=allow_no_other_outputs,
            bypass_env_check=bypass_env_check,
        )
        self.final = final

        if self.skip():
            self.final = True
            return

        # recursively parse again so long as each iteration has fewer undefined jinja variables
        undefined_jinja_vars = ()
        while set(undefined_jinja_vars) != set(self.undefined_jinja_vars):
            undefined_jinja_vars = self.undefined_jinja_vars
            self.parse_again(
                permit_undefined_jinja=True,
                allow_no_other_outputs=allow_no_other_outputs,
                bypass_env_check=bypass_env_check,
            )
            self.final = final

        # always parse again at the end without permit_undefined_jinja
        self.parse_again(
            permit_undefined_jinja=False,
            allow_no_other_outputs=allow_no_other_outputs,
            bypass_env_check=bypass_env_check,
        )
        self.final = final

    @classmethod
    def fromstring(cls, metadata, config=None, variant=None):
        m = super().__new__(cls)
        m.path = ""
        m._meta_path = ""
        m.requirements_path = ""
        config = config or Config(variant=variant)
        m.meta = parse(metadata, config=config, path="")
        m.config = config
        m.parse_again(permit_undefined_jinja=True)
        return m

    @classmethod
    def fromdict(cls, metadata, config=None, variant=None):
        """
        Create a MetaData object from metadata dict directly.
        """
        m = super().__new__(cls)
        m.path = ""
        m._meta_path = ""
        m.requirements_path = ""
        m.meta = sanitize(metadata)
        m.config = config or Config(variant=variant)
        m.undefined_jinja_vars = []
        m.final = False
        return m

    @overload
    def get_section(self, section: Literal["source", "outputs"]) -> list[dict]: ...

    @overload
    def get_section(
        self,
        section: Literal[
            "package",
            "build",
            "requirements",
            "app",
            "test",
            "about",
            "extra",
        ],
    ) -> dict: ...

    def get_section(self, name):
        section = self.meta.get(name)
        if name in OPTIONALLY_ITERABLE_FIELDS:
            if not section:
                return []
            elif isinstance(section, dict):
                return [section]
            elif not isinstance(section, list):
                raise ValueError(f"Expected {name} to be a list")
        else:
            if not section:
                return {}
            elif not isinstance(section, dict):
                raise ValueError(f"Expected {name} to be a dict")
        return section

    def get_value(self, name, default=None, autotype=True):
        """
        Get a value from a meta.yaml.
        :param field: Field to return, e.g. 'package/name'.
                      If the section might be a list, specify an index,
                      e.g. 'source/0/git_url'.
        :param default: Default object to return if field doesn't exist
        :param autotype: If True, return the default type of field if one exists.
                         False will return the default object.
        :return: The named value from meta.yaml
        """
        names = name.split("/")
        assert len(names) in (2, 3), "Bad field name: " + name
        if len(names) == 2:
            section, key = names
            index = None
        elif len(names) == 3:
            section, index, key = names
            assert section in OPTIONALLY_ITERABLE_FIELDS, (
                "Section is not a list: " + section
            )
            index = int(index)

        # get correct default
        if autotype and default is None and FIELDS.get(section, {}).get(key):
            default = FIELDS[section][key]()

        section_data = self.get_section(section)
        if isinstance(section_data, dict):
            assert (
                not index
            ), f"Got non-zero index ({index}), but section {section} is not a list."
        elif isinstance(section_data, list):
            # The 'source' section can be written a list, in which case the name
            # is passed in with an index, e.g. get_value('source/0/git_url')
            if index is None:
                log = utils.get_logger(__name__)
                log.warning(
                    f"No index specified in get_value('{name}'). Assuming index 0."
                )
                index = 0

            if not section_data:
                section_data = {}
            else:
                section_data = section_data[index]
                assert isinstance(
                    section_data, dict
                ), f"Expected {section}/{index} to be a dict"

        value = section_data.get(key, default)

        # handle yaml 1.1 boolean values
        if isinstance(value, str):
            if value.lower() in TRUES:
                value = True
            elif value.lower() in FALSES:
                value = False

        if value is None:
            value = default

        return value

    def check_fields(self):
        def check_field(key, section):
            if key not in FIELDS[section]:
                raise ValueError(f"in section {section!r}: unknown key {key!r}")

        for section, submeta in self.meta.items():
            # anything goes in the extra section
            if section == "extra":
                continue
            if section not in FIELDS:
                raise ValueError(f"unknown section: {section}")
            for key_or_dict in submeta:
                if section in OPTIONALLY_ITERABLE_FIELDS and isinstance(
                    key_or_dict, dict
                ):
                    for key in key_or_dict.keys():
                        check_field(key, section)
                else:
                    check_field(key_or_dict, section)
        return True

    def name(self) -> str:
        name = self.get_value("package/name", "")
        if not name and self.final:
            sys.exit(f"Error: package/name missing in: {self.meta_path!r}")
        name = str(name)
        if name != name.lower():
            sys.exit(f"Error: package/name must be lowercase, got: {name!r}")
        check_bad_chrs(name, "package/name")
        return name

    def version(self) -> str:
        version = self.get_value("package/version", "")
        if not version and not self.get_section("outputs") and self.final:
            sys.exit(f"Error: package/version missing in: {self.meta_path!r}")
        version = str(version)
        check_bad_chrs(version, "package/version")
        if self.final and version.startswith("."):
            raise ValueError(
                "Fully-rendered version can't start with period -  got %s", version
            )
        return version

    def build_number(self):
        number = self.get_value("build/number")

        # build number can come back as None if no setting (or jinja intermediate)
        if not number:
            return 0

        try:
            return int(number)
        except (ValueError, TypeError):
            raise ValueError(
                f"Build number was invalid value '{number}'. Must be an integer."
            )

    def get_depends_top_and_out(self, typ):
        meta_requirements = ensure_list(self.get_value("requirements/" + typ, []))[:]
        req_names = {req.split()[0] for req in meta_requirements if req}
        extra_reqs = []
        # this is for the edge case of requirements for top-level being
        # partially defined in a similarly named output
        if not self.is_output:
            matching_output = [
                out
                for out in self.get_section("outputs")
                if out.get("name") == self.name()
            ]
            if matching_output:
                extra_reqs = utils.expand_reqs(
                    matching_output[0].get("requirements", [])
                ).get(typ, [])
                extra_reqs = [
                    dep for dep in extra_reqs if dep.split()[0] not in req_names
                ]
        meta_requirements = [
            req for req in (set(meta_requirements) | set(extra_reqs)) if req
        ]
        return meta_requirements

    def ms_depends(self, typ="run"):
        names = ("python", "numpy", "perl", "lua")
        name_ver_list = [
            (name, self.config.variant[name])
            for name in names
            if self.config.variant.get(name)
        ]
        if self.config.variant.get("r_base"):
            # r is kept for legacy installations, r-base deprecates it.
            name_ver_list.extend(
                [
                    ("r", self.config.variant["r_base"]),
                    ("r-base", self.config.variant["r_base"]),
                ]
            )
        specs = OrderedDict()
        for spec in ensure_list(self.get_value("requirements/" + typ, [])):
            if not spec:
                continue
            try:
                ms = MatchSpec(spec)
            except AssertionError:
                raise RuntimeError(f"Invalid package specification: {spec!r}")
            except (AttributeError, ValueError) as e:
                raise RuntimeError(
                    "Received dictionary as spec.  Note that pip requirements are "
                    "not supported in conda-build meta.yaml.  Error message: " + str(e)
                )
            if ms.name == self.name() and not (
                typ == "build" and self.config.host_subdir != self.config.build_subdir
            ):
                raise RuntimeError(f"{self.name()} cannot depend on itself")
            for name, ver in name_ver_list:
                if ms.name == name:
                    if self.noarch:
                        continue

            for c in "=!@#$%^&*:;\"'\\|<>?/":
                if c in ms.name:
                    sys.exit(
                        f"Error: bad character '{c}' in package name "
                        f"dependency '{ms.name}'"
                    )
            parts = spec.split()
            if len(parts) >= 2:
                if parts[1] in {">", ">=", "=", "==", "!=", "<", "<="}:
                    msg = (
                        f"Error: bad character '{parts[1]}' in package version "
                        f"dependency '{ms.name}'"
                    )
                    if len(parts) >= 3:
                        msg += f"\nPerhaps you meant '{ms.name} {parts[1]}{parts[2]}'"
                    sys.exit(msg)
            specs[spec] = ms
        return list(specs.values())

    def get_hash_contents(self):
        """
        # A hash will be added if all of these are true for any dependency:
        #
        # 1. package is an explicit dependency in build, host, or run deps
        # 2. package has a matching entry in conda_build_config.yaml which is a pin to a specific
        #    version, not a lower bound
        # 3. that package is not ignored by ignore_version
        #
        # The hash is computed based on the pinning value, NOT the build
        #    dependency build string. This means hashes won't change as often,
        #    but it also means that if run_exports is overly permissive,
        #    software may break more often.
        #
        # A hash will also ALWAYS be added when a compiler package is a build
        #    or host dependency. Reasoning for that is that the compiler
        #    package represents compiler flags and other things that can and do
        #    dramatically change compatibility. It is much more risky to drop
        #    this info (by dropping the hash) than it is for other software.

        # used variables - anything with a value in conda_build_config.yaml that applies to this
        #    recipe.  Includes compiler if compiler jinja2 function is used.
        """
        dependencies = set(self.get_used_vars())

        trim_build_only_deps(self, dependencies)

        # filter out ignored versions
        build_string_excludes = ["python", "r_base", "perl", "lua"]
        build_string_excludes.extend(
            ensure_list(self.config.variant.get("ignore_version", []))
        )
        if "numpy" in dependencies:
            pin_compatible, not_xx = self.uses_numpy_pin_compatible_without_xx
            # numpy_xx means it is accounted for in the build string, with npXYY
            # if not pin_compatible, then we don't care about the usage, and omit it from the hash.
            if self.numpy_xx or (pin_compatible and not not_xx):
                build_string_excludes.append("numpy")
        # always exclude older stuff that's always in the build string (py, np, pl, r, lua)
        if build_string_excludes:
            exclude_pattern = re.compile(
                "|".join(rf"{exc}[\s$]?.*" for exc in build_string_excludes)
            )
            dependencies = [
                req
                for req in dependencies
                if not exclude_pattern.match(req) or " " in self.config.variant[req]
            ]

        # retrieve values - this dictionary is what makes up the hash.

        # if dependencies are only 'target_platform' then ignore that.
        if dependencies == ["target_platform"]:
            hash_contents = {}
        else:
            hash_contents = {key: self.config.variant[key] for key in dependencies}

        # include virtual packages in run
        run_reqs = self.meta.get("requirements", {}).get("run", [])
        virtual_pkgs = [req for req in run_reqs if req.startswith("__")]

        # add name -> match spec mapping for virtual packages
        hash_contents.update({pkg.split(" ")[0]: pkg for pkg in virtual_pkgs})
        return hash_contents

    def hash_dependencies(self):
        """With arbitrary pinning, we can't depend on the build string as done in
        build_string_from_metadata - there's just too much info.  Instead, we keep that as-is, to
        not be disruptive, but we add this extra hash, which is just a way of distinguishing files
        on disk.  The actual determination of dependencies is done in the repository metadata.

        This was revised in conda-build 3.1.0: hashing caused too many package
            rebuilds. We reduce the scope to include only the pins added by conda_build_config.yaml,
            and no longer hash files that contribute to the recipe.
        """
        hash_ = ""
        hashing_dependencies = self.get_hash_contents()
        if hashing_dependencies:
            return _hash_dependencies(hashing_dependencies, self.config.hash_length)
        return hash_

    def build_id(self):
        manual_build_string = self.get_value("build/string")
        # we need the raw recipe for this metadata (possibly an output), so that we can say whether
        #    PKG_HASH is used for anything.
        raw_recipe_text = self.extract_package_and_build_text()
        if not manual_build_string and not raw_recipe_text:
            raise RuntimeError(
                f"Couldn't extract raw recipe text for {self.name()} output"
            )
        raw_manual_build_string = re.search(r"\s*string:", raw_recipe_text)
        # user setting their own build string.  Don't modify it.
        if manual_build_string and not (
            raw_manual_build_string
            and re.findall(r"h\{\{\s*PKG_HASH\s*\}\}", raw_manual_build_string.string)
        ):
            check_bad_chrs(manual_build_string, "build/string")
            out = manual_build_string
        else:
            # default; build/string not set or uses PKG_HASH variable, so we should fill in the hash
            out = build_string_from_metadata(self)
            if self.config.filename_hashing and self.final:
                hash_ = self.hash_dependencies()
                if not re.findall(f"h[0-9a-f]{{{self.config.hash_length}}}", out):
                    ret = out.rsplit("_", 1)
                    try:
                        int(ret[0])
                        out = "_".join((hash_, str(ret[0]))) if hash_ else str(ret[0])
                    except ValueError:
                        out = ret[0] + hash_
                    if len(ret) > 1:
                        out = "_".join([out] + ret[1:])
                else:
                    out = re.sub(f"h[0-9a-f]{{{self.config.hash_length}}}", hash_, out)
        return out

    def dist(self):
        return f"{self.name()}-{self.version()}-{self.build_id()}"

    def pkg_fn(self):
        return f"{self.dist()}.tar.bz2"

    def is_app(self):
        return bool(self.get_value("app/entry"))

    def app_meta(self):
        d = {"type": "app"}
        if self.get_value("app/icon"):
            d["icon"] = "{}.png".format(
                compute_sum(join(self.path, self.get_value("app/icon")), "md5")
            )

        for field, key in [
            ("app/entry", "app_entry"),
            ("app/type", "app_type"),
            ("app/cli_opts", "app_cli_opts"),
            ("app/summary", "summary"),
            ("app/own_environment", "app_own_environment"),
        ]:
            value = self.get_value(field)
            if value:
                d[key] = value
        return d

    def info_index(self):
        arch = (
            "noarch" if self.config.target_subdir == "noarch" else self.config.host_arch
        )
        d = dict(
            name=self.name(),
            version=self.version(),
            build=self.build_id(),
            build_number=self.build_number(),
            platform=self.config.host_platform
            if (self.config.host_platform != "noarch" and arch != "noarch")
            else None,
            arch=ARCH_MAP.get(arch, arch),
            subdir=self.config.target_subdir,
            depends=sorted(" ".join(ms.spec.split()) for ms in self.ms_depends()),
            timestamp=int(time.time() * 1000),
        )
        for key in ("license", "license_family"):
            value = self.get_value("about/" + key)
            if value:
                d[key] = value

        preferred_env = self.get_value("build/preferred_env")
        if preferred_env:
            d["preferred_env"] = preferred_env

        # conda 4.4+ optional dependencies
        constrains = ensure_list(self.get_value("requirements/run_constrained"))
        # filter None values
        constrains = [v for v in constrains if v]
        if constrains:
            d["constrains"] = constrains

        if self.get_value("build/features"):
            d["features"] = " ".join(self.get_value("build/features"))
        if self.get_value("build/track_features"):
            d["track_features"] = " ".join(self.get_value("build/track_features"))
        if self.get_value("build/provides_features"):
            d["provides_features"] = self.get_value("build/provides_features")
        if self.get_value("build/requires_features"):
            d["requires_features"] = self.get_value("build/requires_features")
        if self.noarch:
            d["platform"] = d["arch"] = None
            d["subdir"] = "noarch"
            # These are new-style noarch settings.  the self.noarch setting can be True in 2 ways:
            #    if noarch: True or if noarch_python: True.  This is disambiguation.
            build_noarch = self.get_value("build/noarch")
            if build_noarch:
                d["noarch"] = build_noarch
        if self.is_app():
            d.update(self.app_meta())
        return d

    def has_prefix_files(self):
        ret = ensure_list(self.get_value("build/has_prefix_files", []))
        if not isinstance(ret, list):
            raise RuntimeError("build/has_prefix_files should be a list of paths")
        if on_win:
            if any("\\" in i for i in ret):
                raise RuntimeError(
                    "build/has_prefix_files paths must use / "
                    "as the path delimiter on Windows"
                )
        return expand_globs(ret, self.config.host_prefix)

    def ignore_prefix_files(self):
        ret = self.get_value("build/ignore_prefix_files", False)
        if not isinstance(ret, (list, bool)):
            raise RuntimeError(
                "build/ignore_prefix_files should be boolean or a list of paths "
                "(optionally globs)"
            )
        if on_win:
            if isinstance(ret, list) and any("\\" in i for i in ret):
                raise RuntimeError(
                    "build/ignore_prefix_files paths must use / "
                    "as the path delimiter on Windows"
                )
        return (
            expand_globs(ret, self.config.host_prefix) if isinstance(ret, list) else ret
        )

    def always_include_files(self):
        files = ensure_list(self.get_value("build/always_include_files", []))
        if any("\\" in i for i in files):
            raise RuntimeError(
                "build/always_include_files paths must use / "
                "as the path delimiter on Windows"
            )
        if on_win:
            files = [f.replace("/", "\\") for f in files]

        return expand_globs(files, self.config.host_prefix)

    def ignore_verify_codes(self):
        return ensure_list(self.get_value("build/ignore_verify_codes", []))

    def binary_relocation(self):
        ret = self.get_value("build/binary_relocation", True)
        if not isinstance(ret, (list, bool)):
            raise RuntimeError(
                "build/binary_relocation should be boolean or a list of paths "
                "(optionally globs)"
            )
        if on_win:
            if isinstance(ret, list) and any("\\" in i for i in ret):
                raise RuntimeError(
                    "build/binary_relocation paths must use / "
                    "as the path delimiter on Windows"
                )
        return (
            expand_globs(ret, self.config.host_prefix) if isinstance(ret, list) else ret
        )

    def include_recipe(self) -> bool:
        return bool(self.get_value("build/include_recipe", True))

    def binary_has_prefix_files(self):
        ret = ensure_list(self.get_value("build/binary_has_prefix_files", []))
        if not isinstance(ret, list):
            raise RuntimeError(
                "build/binary_has_prefix_files should be a list of paths"
            )
        if on_win:
            if any("\\" in i for i in ret):
                raise RuntimeError(
                    "build/binary_has_prefix_files paths must use / "
                    "as the path delimiter on Windows"
                )
        return expand_globs(ret, self.config.host_prefix)

    def skip(self) -> bool:
        return bool(self.get_value("build/skip", False))

    def _get_contents(
        self,
        permit_undefined_jinja,
        allow_no_other_outputs=False,
        bypass_env_check=False,
        template_string=None,
        skip_build_id=False,
        alt_name=None,
        variant=None,
    ):
        """
        Get the contents of our [meta.yaml|conda.yaml] file.
        If jinja is installed, then the template.render function is called
        before standard conda macro processors.

        permit_undefined_jinja: If True, *any* use of undefined jinja variables will
                                evaluate to an emtpy string, without emitting an error.
        """
        try:
            import jinja2
        except ImportError:
            print("There was an error importing jinja2.", file=sys.stderr)
            print(
                "Please run `conda install jinja2` to enable jinja template support",
                file=sys.stderr,
            )  # noqa
            with open(self.meta_path) as fd:
                return fd.read()

        from .jinja_context import (
            FilteredLoader,
            UndefinedNeverFail,
            context_processor,
        )

        path, filename = os.path.split(self.meta_path)
        loaders = [  # search relative to '<conda_root>/Lib/site-packages/conda_build/templates'
            jinja2.PackageLoader("conda_build"),
            # search relative to RECIPE_DIR
            jinja2.FileSystemLoader(path),
        ]

        # search relative to current conda environment directory
        conda_env_path = os.environ.get(
            "CONDA_DEFAULT_ENV"
        )  # path to current conda environment
        if conda_env_path and os.path.isdir(conda_env_path):
            conda_env_path = os.path.abspath(conda_env_path)
            conda_env_path = conda_env_path.replace("\\", "/")  # need unix-style path
            env_loader = jinja2.FileSystemLoader(conda_env_path)
            loaders.append(jinja2.PrefixLoader({"$CONDA_DEFAULT_ENV": env_loader}))

        undefined_type = jinja2.StrictUndefined
        if permit_undefined_jinja:
            # The UndefinedNeverFail class keeps a global list of all undefined names
            # Clear any leftover names from the last parse.
            UndefinedNeverFail.all_undefined_names = []
            undefined_type = UndefinedNeverFail

        loader = FilteredLoader(jinja2.ChoiceLoader(loaders), config=self.config)
        env = jinja2.Environment(loader=loader, undefined=undefined_type)

        from .environ import get_dict

        env.globals.update(get_selectors(self.config))
        env.globals.update(get_dict(m=self, skip_build_id=skip_build_id))
        env.globals.update({"CONDA_BUILD_STATE": "RENDER"})
        env.globals.update(
            context_processor(
                self,
                path,
                config=self.config,
                permit_undefined_jinja=permit_undefined_jinja,
                allow_no_other_outputs=allow_no_other_outputs,
                bypass_env_check=bypass_env_check,
                skip_build_id=skip_build_id,
                variant=variant,
            )
        )
        # override PKG_NAME with custom value.  This gets used when an output needs to pretend
        #   that it is top-level when getting the top-level recipe data.
        if alt_name:
            env.globals.update({"PKG_NAME": alt_name})

        # Future goal here.  Not supporting jinja2 on replaced sections right now.

        # we write a temporary file, so that we can dynamically replace sections in the meta.yaml
        #     file on disk.  These replaced sections also need to have jinja2 filling in templates.
        # The really hard part here is that we need to operate on plain text, because we need to
        #     keep selectors and all that.

        try:
            if template_string:
                template = env.from_string(template_string)
            elif filename:
                template = env.get_or_select_template(filename)
            else:
                template = env.from_string("")

            os.environ["CONDA_BUILD_STATE"] = "RENDER"
            rendered = template.render(environment=env)

            if permit_undefined_jinja:
                self.undefined_jinja_vars = UndefinedNeverFail.all_undefined_names
            else:
                self.undefined_jinja_vars = []

        except jinja2.TemplateError as ex:
            if "'None' has not attribute" in str(ex):
                ex = "Failed to run jinja context function"
            raise CondaBuildUserError(
                f"Failed to render jinja template in {self.meta_path}:\n{str(ex)}"
            )
        finally:
            if "CONDA_BUILD_STATE" in os.environ:
                del os.environ["CONDA_BUILD_STATE"]
        return rendered

    def __unicode__(self):
        """
        String representation of the MetaData.
        """
        return str(self.__dict__)

    def __str__(self):
        return self.__unicode__()

    def __repr__(self):
        """
        String representation of the MetaData.
        """
        return self.__str__()

    @property
    def meta_path(self):
        meta_path = (
            self._meta_path
            # get the parent recipe path if this is a subpackage
            or self.get_value("extra/parent_recipe", {}).get("path", "")
        )
        if meta_path and os.path.basename(meta_path) != self._meta_name:
            meta_path = os.path.join(meta_path, self._meta_name)
        return meta_path

    @property
    def uses_setup_py_in_meta(self):
        meta_text = ""
        if self.meta_path:
            with open(self.meta_path, "rb") as f:
                meta_text = UnicodeDammit(f.read()).unicode_markup
        return "load_setup_py_data" in meta_text or "load_setuptools" in meta_text

    @property
    def uses_regex_in_meta(self):
        meta_text = ""
        if self.meta_path:
            with open(self.meta_path, "rb") as f:
                meta_text = UnicodeDammit(f.read()).unicode_markup
        return "load_file_regex" in meta_text

    @property
    def uses_load_file_data_in_meta(self):
        meta_text = ""
        if self.meta_path:
            with open(self.meta_path, "rb") as f:
                meta_text = UnicodeDammit(f.read()).unicode_markup
        return "load_file_data" in meta_text

    @property
    def needs_source_for_render(self):
        return (
            self.uses_vcs_in_meta
            or self.uses_setup_py_in_meta
            or self.uses_regex_in_meta
            or self.uses_load_file_data_in_meta
        )

    @property
    def uses_jinja(self):
        if not self.meta_path:
            return False
        with open(self.meta_path, "rb") as f:
            meta_text = UnicodeDammit(f.read()).unicode_markup
            matches = re.findall(r"{{.*}}", meta_text)
        return len(matches) > 0

    @property
    def uses_vcs_in_meta(self) -> Literal["git", "svn", "mercurial"] | None:
        """returns name of vcs used if recipe contains metadata associated with version control systems.
        If this metadata is present, a download/copy will be forced in parse_or_try_download.
        """
        vcs = None
        vcs_types = ["git", "svn", "hg"]
        # We would get here if we use Jinja2 templating, but specify source with path.
        if self.meta_path:
            with open(self.meta_path, "rb") as f:
                meta_text = UnicodeDammit(f.read()).unicode_markup
                for _vcs in vcs_types:
                    matches = re.findall(rf"{_vcs.upper()}_[^\.\s\'\"]+", meta_text)
                    if len(matches) > 0 and _vcs != self.get_value("package/name"):
                        if _vcs == "hg":
                            _vcs = "mercurial"
                        vcs = _vcs
                        break
        return vcs

    @property
    def uses_vcs_in_build(self) -> Literal["git", "svn", "mercurial"] | None:
        # TODO :: Re-work this. Is it even useful? We can declare any vcs in our build deps.
        build_script = "bld.bat" if on_win else "build.sh"
        build_script = os.path.join(self.path, build_script)
        for recipe_file in (build_script, self.meta_path):
            if os.path.isfile(recipe_file):
                vcs_types = ["git", "svn", "hg"]
                with open(self.meta_path, "rb") as f:
                    build_script = UnicodeDammit(f.read()).unicode_markup
                    for vcs in vcs_types:
                        # commands are assumed to have 3 parts:
                        #   1. the vcs command, optionally with an exe extension
                        #   2. a subcommand - for example, "clone"
                        #   3. a target url or other argument
                        matches = re.findall(
                            rf"{vcs}(?:\.exe)?(?:\s+\w+\s+[\w\/\.:@]+)",
                            build_script,
                            flags=re.IGNORECASE,
                        )
                        if len(matches) > 0 and vcs != self.get_value("package/name"):
                            if vcs == "hg":
                                vcs = "mercurial"
                            return vcs
        return None

    def get_recipe_text(
        self,
        extract_pattern: str | None = None,
        force_top_level: bool = False,
        apply_selectors: bool = True,
    ) -> str:
        meta_path = self.meta_path
        if meta_path:
            recipe_text = read_meta_file(meta_path)
            if self.is_output and not force_top_level:
                recipe_text = self.extract_single_output_text(
                    self.name(), getattr(self, "type", None)
                )
        else:
            from .render import output_yaml

            recipe_text = output_yaml(self)
        recipe_text = _filter_recipe_text(recipe_text, extract_pattern)
        if apply_selectors:
            recipe_text = select_lines(
                recipe_text,
                get_selectors(self.config),
                variants_in_place=bool(self.config.variant),
            )
        return recipe_text.rstrip()

    def extract_requirements_text(self, force_top_level=False):
        # outputs are already filtered into each output for us
        f = r"(^\s*requirements:.*?)(?=^\s*test:|^\s*extra:|^\s*about:|^\s*-\s+name:|^outputs:|\Z)"
        if "package:" in self.get_recipe_text(force_top_level=force_top_level):
            # match top-level requirements - start of line means top-level requirements
            #    ^requirements:.*?
            # match output with similar name
            #    (?:-\s+name:\s+%s.*?)requirements:.*?
            # terminate match of other sections
            #    (?=^\s*-\sname|^\s*test:|^\s*extra:|^\s*about:|^outputs:|\Z)
            f = r"(^requirements:.*?)(?=^test:|^extra:|^about:|^outputs:|\Z)"
        return self.get_recipe_text(f, force_top_level=force_top_level)

    def extract_outputs_text(self, apply_selectors=True):
        return self.get_recipe_text(
            r"(^outputs:.*?)(?=^test:|^extra:|^about:|\Z)",
            force_top_level=True,
            apply_selectors=apply_selectors,
        )

    def extract_source_text(self):
        return self.get_recipe_text(
            r"(\s*source:.*?)(?=^build:|^requirements:|^test:|^extra:|^about:|^outputs:|\Z)"
        )

    def extract_package_and_build_text(self):
        return self.get_recipe_text(
            r"(^.*?)(?=^requirements:|^test:|^extra:|^about:|^outputs:|\Z)"
        )

    def extract_single_output_text(
        self, output_name, output_type, apply_selectors=True
    ):
        # first, need to figure out which index in our list of outputs the name matches.
        #    We have to do this on rendered data, because templates can be used in output names
        recipe_text = self.extract_outputs_text(apply_selectors=apply_selectors)
        output_matches = output_re.findall(recipe_text)
        outputs = self.meta.get("outputs") or (
            self.parent_outputs if hasattr(self, "parent_outputs") else None
        )
        if not outputs:
            outputs = [{"name": self.name()}]

        try:
            if output_type:
                output_tuples = [
                    (
                        out.get("name", self.name()),
                        out.get(
                            "type",
                            "conda_v2"
                            if self.config.conda_pkg_format == "2"
                            else "conda",
                        ),
                    )
                    for out in outputs
                ]
                output_index = output_tuples.index((output_name, output_type))
            else:
                output_tuples = [out.get("name", self.name()) for out in outputs]
                output_index = output_tuples.index(output_name)
            output = output_matches[output_index] if output_matches else ""
        except ValueError:
            if not self.path and self.meta.get("extra", {}).get("parent_recipe"):
                utils.get_logger(__name__).warning(
                    f"Didn't match any output in raw metadata.  Target value was: {output_name}"
                )
                output = ""
            else:
                output = self.name()
        return output

    @property
    def numpy_xx(self) -> bool:
        """This is legacy syntax that we need to support for a while.  numpy x.x means
        "pin run as build" for numpy.  It was special-cased to only numpy."""
        text = self.extract_requirements_text()
        return bool(numpy_xx_re.search(text))

    @property
    def uses_numpy_pin_compatible_without_xx(self) -> tuple[bool, bool]:
        text = self.extract_requirements_text()
        compatible_search = numpy_compatible_re.search(text)
        max_pin_search = None
        if compatible_search:
            max_pin_search = numpy_compatible_x_re.search(text)
        # compatible_search matches simply use of pin_compatible('numpy')
        # max_pin_search quantifies the actual number of x's in the max_pin field.  The max_pin
        #     field can be absent, which is equivalent to a single 'x'
        return (
            bool(compatible_search),
            max_pin_search.group(1).count("x") != 2 if max_pin_search else True,
        )

    @property
    def uses_subpackage(self):
        outputs = self.get_section("outputs")
        in_reqs = False
        for out in outputs:
            if "name" in out:
                name_re = re.compile(r"^{}(\s|\Z|$)".format(out["name"]))
                in_reqs = any(
                    name_re.match(req) for req in self.get_depends_top_and_out("run")
                )
                if in_reqs:
                    break
        subpackage_pin = False
        if not in_reqs and self.meta_path:
            data = self.extract_requirements_text(force_top_level=True)
            if data:
                subpackage_pin = re.search(r"{{\s*pin_subpackage\(.*\)\s*}}", data)
        return in_reqs or bool(subpackage_pin)

    @property
    def uses_new_style_compiler_activation(self):
        text = self.extract_requirements_text()
        return bool(re.search(r"\{\{\s*compiler\(.*\)\s*\}\}", text))

    def validate_features(self):
        if any(
            "-" in feature for feature in ensure_list(self.get_value("build/features"))
        ):
            raise ValueError(
                "- is a disallowed character in features.  Please change this "
                "character in your recipe."
            )

    def copy(self: Self) -> MetaData:
        new = copy.copy(self)
        new.config = self.config.copy()
        new.meta = copy.deepcopy(self.meta)
        new.type = getattr(
            self, "type", "conda_v2" if self.config.conda_pkg_format == "2" else "conda"
        )
        return new

    @property
    def noarch(self):
        return self.get_value("build/noarch")

    @noarch.setter
    def noarch(self, value: str | None) -> None:
        self.meta.setdefault("build", {})["noarch"] = value
        if not self.noarch_python and not value:
            self.config.reset_platform()
        elif value:
            self.config.host_platform = "noarch"

    @property
    def noarch_python(self) -> bool:
        return bool(self.get_value("build/noarch_python"))

    @noarch_python.setter
    def noarch_python(self, value: bool) -> None:
        self.meta.setdefault("build", {})["noarch_python"] = value
        if not self.noarch and not value:
            self.config.reset_platform()
        elif value:
            self.config.host_platform = "noarch"

    @property
    def variant_in_source(self):
        variant = self.config.variant
        self.config.variant = {}
        self.parse_again(
            permit_undefined_jinja=True,
            allow_no_other_outputs=True,
            bypass_env_check=True,
        )
        vars_in_recipe = set(self.undefined_jinja_vars)
        self.config.variant = variant

        for key in vars_in_recipe & set(variant.keys()):
            # We use this variant in the top-level recipe.
            # constrain the stored variants to only this version in the output
            #     variant mapping
            if re.search(
                rf"\s*\{{\{{\s*{key}\s*(?:.*?)?\}}\}}", self.extract_source_text()
            ):
                return True
        return False

    @property
    def pin_depends(self):
        return self.get_value("build/pin_depends", "").lower()

    @property
    def source_provided(self):
        return not self.get_section("source") or (
            os.path.isdir(self.config.work_dir) and os.listdir(self.config.work_dir)
        )

    def reconcile_metadata_with_output_dict(self, output_metadata, output_dict):
        output_metadata.meta["package"]["name"] = output_dict.get("name", self.name())

        # make sure that subpackages do not duplicate tests from top-level recipe
        test = output_metadata.meta.get("test", {})
        if output_dict.get("name") != self.name() or not (
            output_dict.get("script") or output_dict.get("files")
        ):
            if "commands" in test:
                del test["commands"]
            if "imports" in test:
                del test["imports"]

        # make sure that subpackages do not duplicate top-level entry-points or run_exports
        build = output_metadata.meta.get("build", {})
        transfer_keys = "entry_points", "run_exports", "script"
        for key in transfer_keys:
            if key in output_dict:
                build[key] = output_dict[key]
            elif key in build:
                del build[key]
        output_metadata.meta["build"] = build

        # reset this so that reparsing does not reset the metadata name
        output_metadata._meta_path = ""

    def get_output_metadata(self, output):
        if output.get("name") == self.name():
            output_metadata = self.copy()
            output_metadata.type = output.get(
                "type", "conda_v2" if self.config.conda_pkg_format == "2" else "conda"
            )

        else:
            output_metadata = self.copy()
            output_reqs = utils.expand_reqs(output.get("requirements", {}))
            build_reqs = output_reqs.get("build", [])
            host_reqs = output_reqs.get("host", [])
            run_reqs = output_reqs.get("run", [])
            constrain_reqs = output_reqs.get("run_constrained", [])
            # pass through any other unrecognized req types
            other_reqs = {
                k: v
                for k, v in output_reqs.items()
                if k not in ("build", "host", "run", "run_constrained")
            }

            if output.get("target"):
                output_metadata.config.target_subdir = output["target"]

            if self.name() != output.get("name") or (
                output.get("script") or output.get("files")
            ):
                self.reconcile_metadata_with_output_dict(output_metadata, output)

            output_metadata.type = output.get(
                "type", "conda_v2" if self.config.conda_pkg_format == "2" else "conda"
            )

            if "name" in output:
                # since we are copying reqs from the top-level package, which
                #   can depend on subpackages, make sure that we filter out
                #   subpackages so that they don't depend on themselves
                subpackage_pattern = re.compile(
                    r"(?:^{}(?:\s|$|\Z))".format(output["name"])
                )
                if build_reqs:
                    build_reqs = [
                        req for req in build_reqs if not subpackage_pattern.match(req)
                    ]
                if host_reqs:
                    host_reqs = [
                        req for req in host_reqs if not subpackage_pattern.match(req)
                    ]
                if run_reqs:
                    run_reqs = [
                        req for req in run_reqs if not subpackage_pattern.match(req)
                    ]

            requirements = {}
            requirements.update({"build": build_reqs}) if build_reqs else None
            requirements.update({"host": host_reqs}) if host_reqs else None
            requirements.update({"run": run_reqs}) if run_reqs else None
            requirements.update(
                {"run_constrained": constrain_reqs}
            ) if constrain_reqs else None
            requirements.update(other_reqs)
            output_metadata.meta["requirements"] = requirements

            output_metadata.meta["package"]["version"] = (
                output.get("version") or self.version()
            )
            output_metadata.final = False
            output_metadata.noarch = output.get("noarch", False)
            output_metadata.noarch_python = output.get("noarch_python", False)
            # primarily for tests - make sure that we keep the platform consistent (setting noarch
            #      would reset it)
            if (
                not (output_metadata.noarch or output_metadata.noarch_python)
                and self.config.platform != output_metadata.config.platform
            ):
                output_metadata.config.platform = self.config.platform

            build = output_metadata.meta.get("build", {})
            # legacy (conda build 2.1.x - 3.0.25). Newer stuff should just emulate
            #   the top-level recipe, with full sections for build, test, about
            if "number" in output:
                build["number"] = output["number"]
            if "string" in output:
                build["string"] = output["string"]
            if "run_exports" in output and output["run_exports"]:
                build["run_exports"] = output["run_exports"]
            if "track_features" in output and output["track_features"]:
                build["track_features"] = output["track_features"]
            if "features" in output and output["features"]:
                build["features"] = output["features"]

            # 3.0.26+ - just pass through the whole build section from the output.
            #    It clobbers everything else, aside from build number
            if "build" in output:
                build = output["build"]
                if build is None:
                    build = {}
                if "number" not in build:
                    build["number"] = output.get(
                        "number", output_metadata.build_number()
                    )
            output_metadata.meta["build"] = build
            if "test" in output:
                output_metadata.meta["test"] = output["test"]
            if "about" in output:
                output_metadata.meta["about"] = output["about"]
            self.append_parent_metadata(output_metadata)
        return output_metadata

    def append_parent_metadata(self, out_metadata):
        extra = self.meta.get("extra", {})
        extra["parent_recipe"] = {
            "path": self.path,
            "name": self.name(),
            "version": self.version(),
        }
        out_metadata.meta["extra"] = extra

    def get_reduced_variant_set(self, used_variables):
        # reduce variable space to limit work we need to do
        full_collapsed_variants = list_of_dicts_to_dict_of_lists(self.config.variants)
        reduced_collapsed_variants = full_collapsed_variants.copy()
        reduce_keys = set(self.config.variants[0].keys()) - set(used_variables)

        zip_key_groups = self.config.variant.get("zip_keys", [])
        zip_key_groups = (
            [zip_key_groups]
            if zip_key_groups and isinstance(zip_key_groups[0], str)
            else zip_key_groups
        )
        used_zip_key_groups = [
            group for group in zip_key_groups if any(set(group) & set(used_variables))
        ]

        extend_keys = full_collapsed_variants.get("extend_keys", [])
        reduce_keys = [
            key
            for key in reduce_keys
            if not any(key in group for group in used_zip_key_groups)
            and key not in extend_keys
        ]
        for key in reduce_keys:
            values = full_collapsed_variants.get(key)
            if (
                values is not None
                and len(values)
                and not hasattr(values, "keys")
                and key != "zip_keys"
            ):
                # save only one element from this key
                reduced_collapsed_variants[key] = utils.ensure_list(next(iter(values)))

        out = dict_of_lists_to_list_of_dicts(reduced_collapsed_variants)
        return out

    def get_output_metadata_set(
        self,
        permit_undefined_jinja: bool = False,
        permit_unsatisfiable_variants: bool = False,
        bypass_env_check: bool = False,
    ) -> list[OutputTuple]:
        from .source import provide

        output_tuples: list[OutputTuple] = []
        if self.final:
            outputs = get_output_dicts_from_metadata(self)
            output_tuples = [(outputs[0], self)]
        else:
            all_output_metadata = OrderedDict()

            used_variables = self.get_used_loop_vars(force_global=True)
            top_loop = (
                self.get_reduced_variant_set(used_variables) or self.config.variants[:1]
            )

            for variant in (
                top_loop
                if (hasattr(self.config, "variants") and self.config.variants)
                else [self.config.variant]
            ):
                ref_metadata = self.copy()
                ref_metadata.config.variant = variant
                if ref_metadata.needs_source_for_render and self.variant_in_source:
                    ref_metadata.parse_again()
                    utils.rm_rf(ref_metadata.config.work_dir)
                    provide(ref_metadata)
                    ref_metadata.parse_again()
                try:
                    ref_metadata.parse_until_resolved(
                        allow_no_other_outputs=True, bypass_env_check=True
                    )
                except SystemExit:
                    pass
                outputs = get_output_dicts_from_metadata(ref_metadata)

                try:
                    for out in outputs:
                        requirements = out.get("requirements")
                        if requirements:
                            requirements = utils.expand_reqs(requirements)
                            for env in ("build", "host", "run"):
                                insert_variant_versions(requirements, variant, env)
                            out["requirements"] = requirements
                        out_metadata = ref_metadata.get_output_metadata(out)

                        # keeping track of other outputs is necessary for correct functioning of the
                        #    pin_subpackage jinja2 function.  It's important that we store all of
                        #    our outputs so that they can be referred to in later rendering.  We
                        #    also refine this collection as each output metadata object is
                        #    finalized - see the finalize_outputs_pass function
                        all_output_metadata[
                            out_metadata.name(),
                            deepfreeze(
                                {
                                    k: out_metadata.config.variant[k]
                                    for k in out_metadata.get_used_vars()
                                }
                            ),
                        ] = (out, out_metadata)
                        output_tuples.append((out, out_metadata))
                        ref_metadata.other_outputs = out_metadata.other_outputs = (
                            all_output_metadata
                        )
                except SystemExit:
                    if not permit_undefined_jinja:
                        raise
                    output_tuples = []

            assert output_tuples, (
                "Error: output metadata set is empty.  Please file an issue"
                " on the conda-build tracker at https://github.com/conda/conda-build/issues"
            )

            render_order: list[OutputTuple] = _toposort_outputs(output_tuples)
            _check_circular_dependencies(render_order, config=self.config)
            conda_packages = OrderedDict()
            non_conda_packages = []

            for output_d, m in render_order:
                if not output_d.get("type") or output_d["type"] in (
                    "conda",
                    "conda_v2",
                ):
                    conda_packages[
                        m.name(),
                        deepfreeze({k: m.config.variant[k] for k in m.get_used_vars()}),
                    ] = (output_d, m)
                elif output_d.get("type") == "wheel":
                    if not output_d.get("requirements", {}).get("build") or not any(
                        "pip" in req for req in output_d["requirements"]["build"]
                    ):
                        build_reqs = output_d.get("requirements", {}).get("build", [])
                        build_reqs.extend(
                            ["pip", "python {}".format(m.config.variant["python"])]
                        )
                        output_d["requirements"] = output_d.get("requirements", {})
                        output_d["requirements"]["build"] = build_reqs
                        m.meta["requirements"] = m.get_section("requirements")
                        m.meta["requirements"]["build"] = build_reqs
                    non_conda_packages.append((output_d, m))
                else:
                    # for wheels and other non-conda packages, just append them at the end.
                    #    no deduplication with hashes currently.
                    # hard part about including any part of output_d
                    #    outside of this func is that it is harder to
                    #    obtain an exact match elsewhere
                    non_conda_packages.append((output_d, m))

            # early stages don't need to do the finalization.  Skip it until the later stages
            #     when we need it.
            if not permit_undefined_jinja and not ref_metadata.skip():
                conda_packages = finalize_outputs_pass(
                    ref_metadata,
                    conda_packages,
                    pass_no=0,
                    permit_unsatisfiable_variants=permit_unsatisfiable_variants,
                    bypass_env_check=bypass_env_check,
                )

                # Sanity check: if any exact pins of any subpackages, make sure that they match
                ensure_matching_hashes(conda_packages)
            final_conda_packages = []
            for out_d, m in conda_packages.values():
                # We arbitrarily mark all output metadata as final, regardless
                #    of if it truly is or not. This is done to add sane hashes
                #    to unfinalizable packages, so that they are differentiable
                #    from one another. This is mostly a test concern than an
                #    actual one, as any "final" recipe returned here will still
                #    barf if anyone tries to actually build it.
                m.final = True
                final_conda_packages.append((out_d, m))
            output_tuples = final_conda_packages + non_conda_packages
        _check_run_constrained(output_tuples)
        return output_tuples

    def get_loop_vars(self, subset=None):
        return get_vars(
            getattr(self.config, "input_variants", self.config.variants), subset=subset
        )

    def get_used_loop_vars(self, force_top_level=False, force_global=False):
        used_vars = self.get_used_vars(
            force_top_level=force_top_level, force_global=force_global
        )
        return self.get_loop_vars(subset=used_vars)

    def get_rendered_recipe_text(
        self, permit_undefined_jinja=False, extract_pattern=None
    ):
        template_string = self.get_recipe_text(
            extract_pattern=extract_pattern, force_top_level=True
        ).rstrip()

        return (
            yaml.safe_load(
                self._get_contents(
                    permit_undefined_jinja=permit_undefined_jinja,
                    template_string=template_string,
                    skip_build_id=False,
                )
            )
            or {}
        )

    def get_rendered_outputs_section(self, permit_undefined_jinja=False, variant=None):
        extract_pattern = r"(.*)package:"
        template_string = "\n".join(
            (
                self.get_recipe_text(
                    extract_pattern=extract_pattern, force_top_level=True
                ),
                # second item: the output text for this metadata
                #    object (might be output)
                self.extract_outputs_text(),
            )
        ).rstrip()

        outputs = (
            yaml.safe_load(
                self._get_contents(
                    permit_undefined_jinja=permit_undefined_jinja,
                    template_string=template_string,
                    skip_build_id=False,
                    allow_no_other_outputs=permit_undefined_jinja,
                    variant=variant,
                )
            )
            or {}
        ).get("outputs", [])
        return get_output_dicts_from_metadata(self, outputs=outputs)

    def get_rendered_output(self, name, permit_undefined_jinja=False, variant=None):
        """This is for obtaining the rendered, parsed, dictionary-object representation of an
        output. It's not useful for saying what variables are used. You need earlier, more raw
        versions of the metadata for that. It is useful, however, for getting updated, re-rendered
        contents of outputs."""
        output = None
        for output_ in self.get_rendered_outputs_section(
            permit_undefined_jinja=permit_undefined_jinja, variant=variant
        ):
            if output_.get("name") == name:
                output = output_
                break
        return output

    @property
    def force_ignore_keys(self):
        return ensure_list(self.get_value("build/force_ignore_keys"))

    @property
    def force_use_keys(self):
        return ensure_list(self.get_value("build/force_use_keys"))

    def get_used_vars(self, force_top_level=False, force_global=False):
        global used_vars_cache
        recipe_dir = self.path

        hashed_variants = deepfreeze(self.config.variant)
        if hasattr(self.config, "used_vars"):
            used_vars = self.config.used_vars
        elif (
            self.name(),
            recipe_dir,
            force_top_level,
            force_global,
            self.config.subdir,
            hashed_variants,
        ) in used_vars_cache:
            used_vars = used_vars_cache[
                (
                    self.name(),
                    recipe_dir,
                    force_top_level,
                    force_global,
                    self.config.subdir,
                    hashed_variants,
                )
            ]
        else:
            meta_yaml_reqs = self._get_used_vars_meta_yaml(
                force_top_level=force_top_level, force_global=force_global
            )
            is_output = "package:" not in self.get_recipe_text()

            if is_output:
                script_reqs = self._get_used_vars_output_script()
            else:
                script_reqs = self._get_used_vars_build_scripts()

            used_vars = meta_yaml_reqs | script_reqs
            # force target_platform to always be included, because it determines behavior
            if "target_platform" in self.config.variant and not self.noarch:
                used_vars.add("target_platform")
            # and channel_targets too.
            if "channel_targets" in self.config.variant:
                used_vars.add("channel_targets")

            if self.force_use_keys or self.force_ignore_keys:
                used_vars = (used_vars - set(self.force_ignore_keys)) | set(
                    self.force_use_keys
                )

            used_vars_cache[
                (
                    self.name(),
                    recipe_dir,
                    force_top_level,
                    force_global,
                    self.config.subdir,
                    hashed_variants,
                )
            ] = used_vars
        return used_vars

    def _get_used_vars_meta_yaml_helper(
        self, force_top_level=False, force_global=False, apply_selectors=False
    ):
        if force_global:
            recipe_text = self.get_recipe_text(
                force_top_level=force_top_level, apply_selectors=apply_selectors
            )
            # a bit hacky.  When we force global, we don't distinguish
            #     between requirements and the rest
            reqs_text = recipe_text
        else:
            if self.is_output and not force_top_level:
                recipe_text = self.extract_single_output_text(
                    self.name(),
                    getattr(self, "type", None),
                    apply_selectors=apply_selectors,
                )
            else:
                recipe_text = self.get_recipe_text(
                    force_top_level=force_top_level, apply_selectors=apply_selectors
                ).replace(
                    self.extract_outputs_text(apply_selectors=apply_selectors).strip(),
                    "",
                ) + self.extract_single_output_text(
                    self.name(),
                    getattr(self, "type", None),
                    apply_selectors=apply_selectors,
                )
            reqs_re = re.compile(
                r"requirements:.+?(?=^\w|\Z|^\s+-\s(?=name|type))", flags=re.M | re.S
            )
            reqs_text = reqs_re.search(recipe_text)
            reqs_text = reqs_text.group() if reqs_text else ""

        return reqs_text, recipe_text

    def _get_used_vars_meta_yaml(self, force_top_level=False, force_global=False):
        # make variant dict hashable so that memoization works
        variant_keys = tuple(sorted(self.config.variant.keys()))

        reqs_text, recipe_text = self._get_used_vars_meta_yaml_helper(
            force_top_level=force_top_level,
            force_global=force_global,
            apply_selectors=False,
        )

        all_used_selectors = find_used_variables_in_text(
            variant_keys, recipe_text, selectors_only=True
        )

        reqs_text, recipe_text = self._get_used_vars_meta_yaml_helper(
            force_top_level=force_top_level,
            force_global=force_global,
            apply_selectors=True,
        )
        all_used_reqs = find_used_variables_in_text(
            variant_keys, recipe_text, selectors_only=False
        )

        all_used = all_used_reqs.union(all_used_selectors)

        # things that are only used in requirements need further consideration,
        #   for omitting things that are only used in run
        if force_global:
            used = all_used
        else:
            requirements_used = find_used_variables_in_text(variant_keys, reqs_text)
            outside_reqs_used = all_used - requirements_used

            requirements_used = trim_build_only_deps(self, requirements_used)
            used = outside_reqs_used | requirements_used

        return used

    def _get_used_vars_build_scripts(self):
        used_vars = set()
        buildsh = os.path.join(self.path, "build.sh")
        if os.path.isfile(buildsh):
            used_vars.update(
                find_used_variables_in_shell_script(self.config.variant, buildsh)
            )
        bldbat = os.path.join(self.path, "bld.bat")
        if self.config.platform == "win" and os.path.isfile(bldbat):
            used_vars.update(
                find_used_variables_in_batch_script(self.config.variant, bldbat)
            )
        return used_vars

    def _get_used_vars_output_script(self):
        this_output = (
            self.get_rendered_output(self.name(), permit_undefined_jinja=True) or {}
        )
        used_vars = set()
        if "script" in this_output:
            script = os.path.join(self.path, this_output["script"])
            if os.path.splitext(script)[1] == ".sh":
                used_vars.update(
                    find_used_variables_in_shell_script(self.config.variant, script)
                )
            elif os.path.splitext(script)[1] == ".bat":
                used_vars.update(
                    find_used_variables_in_batch_script(self.config.variant, script)
                )
            else:
                log = utils.get_logger(__name__)
                log.warning(
                    f"Not detecting used variables in output script {script}; conda-build only knows "
                    "how to search .sh and .bat files right now."
                )
        return used_vars

    def get_variants_as_dict_of_lists(self):
        return list_of_dicts_to_dict_of_lists(self.config.variants)

    def clean(self):
        """This ensures that clean is called with the correct build id"""
        self.config.clean()

    @property
    def activate_build_script(self) -> bool:
        return bool(
            self.config.activate
            and self.get_value("build/activate_in_script") is not False
        )

    @property
    def build_is_host(self) -> bool:
        manual_overrides = (
            self.get_value("build/merge_build_host") is True
            or self.config.build_is_host
        )
        manually_disabled = self.get_value("build/merge_build_host") is False
        return manual_overrides or (
            self.config.subdirs_same
            and not manually_disabled
            and "host" not in self.meta.get("requirements", {})
            and not self.uses_new_style_compiler_activation
        )

    def get_top_level_recipe_without_outputs(self):
        recipe_no_outputs = self.get_recipe_text(force_top_level=True).replace(
            self.extract_outputs_text(), ""
        )
        top_no_outputs = {}
        # because we're an output, calls to PKG_NAME used in the top-level
        #    content will reflect our current name, not the top-level name. We
        #    fix that here by replacing any PKG_NAME instances with the known
        #    parent name
        parent_recipe = self.meta.get("extra", {}).get("parent_recipe", {})
        alt_name = parent_recipe["name"] if self.is_output else None
        if recipe_no_outputs:
            top_no_outputs = yaml.safe_load(
                self._get_contents(
                    False, template_string=recipe_no_outputs, alt_name=alt_name
                )
            )
        return top_no_outputs or {}

    def get_test_deps(self, py_files, pl_files, lua_files, r_files):
        specs = [f"{self.name()} {self.version()} {self.build_id()}"]

        # add packages listed in the run environment and test/requires
        specs.extend(ms.spec for ms in self.ms_depends("run"))
        specs += utils.ensure_list(self.get_value("test/requires", []))

        if py_files:
            # as the tests are run by python, ensure that python is installed.
            # (If they already provided python as a run or test requirement,
            #  this won't hurt anything.)
            specs += ["python"]
        if pl_files:
            # as the tests are run by perl, we need to specify it
            specs += ["perl"]
        if lua_files:
            # not sure how this shakes out
            specs += ["lua"]
        if r_files and not any(s.split()[0] in ("r-base", "mro-base") for s in specs):
            # not sure how this shakes out
            specs += ["r-base"]

        specs.extend(utils.ensure_list(self.config.extra_deps))
        return specs


class MetaDataTuple(NamedTuple):
    metadata: MetaData
    need_download: bool
    need_reparse: bool
