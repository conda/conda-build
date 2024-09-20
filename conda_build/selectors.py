# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import TYPE_CHECKING

from .exceptions import CondaBuildUserError
from .features import feature_list
from .utils import ARCH_MAP, DEFAULT_SUBDIRS, get_logger
from .variants import get_default_variant

if TYPE_CHECKING:
    from typing import Any

    from .config import Config


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
            get_logger(__name__).warning(
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


# this function extracts the variable name from a NameError exception, it has the form of:
# "NameError: name 'var' is not defined", where var is the variable that is not defined. This gets
#    returned
def parse_NameError(error: NameError) -> str:
    if match := re.search("'(.+?)'", str(error)):
        return match.group(1)
    return ""


# We evaluate the selector and return True (keep this line) or False (drop this line)
# If we encounter a NameError (unknown variable in selector), then we replace it by False and
#     re-run the evaluation
def eval_selector(
    selector_string: str, namespace: dict[str, Any], variants_in_place: bool
) -> bool:
    try:
        # TODO: is there a way to do this without eval?  Eval allows arbitrary
        #    code execution.
        return eval(selector_string, namespace, {})
    except NameError as e:
        missing_var = parse_NameError(e)
        if variants_in_place:
            get_logger(__name__).debug(
                f"Treating unknown selector {missing_var!r} as if it was False."
            )
        next_string = selector_string.replace(missing_var, "False")
        return eval_selector(next_string, namespace, variants_in_place)


# Selectors must be either:
# - at end of the line
# - embedded (anywhere) within a comment
#
# Notes:
# - [([^\[\]]+)\] means "find a pair of brackets containing any
#                 NON-bracket chars, and capture the contents"
# - (?(2)[^\(\)]*)$ means "allow trailing characters iff group 2 (#.*) was found."
#                 Skip markdown link syntax.
RE_SELECTOR = re.compile(r"(.+?)\s*(#.*)?\[([^\[\]]+)\](?(2)[^\(\)]*)$")


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
            and (match := RE_SELECTOR.match(line))
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
