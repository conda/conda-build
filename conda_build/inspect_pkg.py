# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from functools import lru_cache
from itertools import groupby
from operator import itemgetter
from os.path import abspath, basename, dirname, exists, join, normcase

from conda_build.conda_interface import (
    display_actions,
    get_index,
    install_actions,
    is_linked,
    linked_data,
    specs_from_args,
)
from conda_build.os_utils.ldd import (
    get_linkages,
    get_package_obj_files,
    get_untracked_obj_files,
)
from conda_build.os_utils.liefldd import codefile_type
from conda_build.os_utils.macho import get_rpaths, human_filetype
from conda_build.utils import (
    comma_join,
    ensure_list,
    get_logger,
    package_has_file,
    rm_rf,
)


@lru_cache(maxsize=None)
def dist_files(prefix, dist):
    meta = is_linked(prefix, dist)
    return set(meta["files"]) if meta else set()


def which_package(in_prefix_path, prefix, avoid_canonical_channel_name=False):
    """
    given the path of a conda installed file iterate over
    the conda packages the file came from.  Usually the iteration yields
    only one package.
    """
    norm_ipp = normcase(in_prefix_path.replace(os.sep, "/"))
    from conda_build.utils import linked_data_no_multichannels

    if avoid_canonical_channel_name:
        fn = linked_data_no_multichannels
    else:
        fn = linked_data
    for dist in fn(prefix):
        # dfiles = set(dist.get('files', []))
        dfiles = dist_files(prefix, dist)
        # TODO :: This is completely wrong when the env is on a case-sensitive FS!
        if any(norm_ipp == normcase(w) for w in dfiles):
            yield dist


def print_object_info(info, key):
    output_string = ""
    for header, group in groupby(sorted(info, key=itemgetter(key)), itemgetter(key)):
        output_string += header + "\n"
        for f_info in sorted(group, key=itemgetter("filename")):
            for data in sorted(f_info):
                if data == key:
                    continue
                if f_info[data] is None:
                    continue
                output_string += f"  {data}: {f_info[data]}\n"
            if len([i for i in f_info if f_info[i] is not None and i != key]) > 1:
                output_string += "\n"
        output_string += "\n"
    return output_string


class _untracked_package:
    def __str__(self):
        return "<untracked>"


untracked_package = _untracked_package()


def check_install(
    packages, platform=None, channel_urls=(), prepend=True, minimal_hint=False
):
    prefix = tempfile.mkdtemp("conda")
    try:
        specs = specs_from_args(packages)
        index = get_index(
            channel_urls=channel_urls, prepend=prepend, platform=platform, prefix=prefix
        )
        actions = install_actions(
            prefix, index, specs, pinned=False, minimal_hint=minimal_hint
        )
        display_actions(actions, index)
        return actions
    finally:
        rm_rf(prefix)
    return None


def print_linkages(depmap, show_files=False):
    # Print system and not found last
    dist_depmap = {}
    for k, v in depmap.items():
        if hasattr(k, "dist_name"):
            k = k.dist_name
        dist_depmap[k] = v

    depmap = dist_depmap
    k = sorted(set(depmap.keys()) - {"system", "not found"})
    all_deps = k if "not found" not in depmap.keys() else k + ["system", "not found"]
    output_string = ""
    for dep in all_deps:
        output_string += "%s:\n" % dep
        if show_files:
            for lib, path, binary in sorted(depmap[dep]):
                output_string += f"    {lib} ({path}) from {binary}\n"
        else:
            for lib, path in sorted(set(map(itemgetter(0, 1), depmap[dep]))):
                output_string += f"    {lib} ({path})\n"
        output_string += "\n"
    return output_string


def replace_path(binary, path, prefix):
    if sys.platform.startswith("linux"):
        return abspath(path)
    elif sys.platform.startswith("darwin"):
        if path == basename(binary):
            return abspath(join(prefix, binary))
        if "@rpath" in path:
            rpaths = get_rpaths(join(prefix, binary))
            if not rpaths:
                return "NO LC_RPATH FOUND"
            else:
                for rpath in rpaths:
                    path1 = path.replace("@rpath", rpath)
                    path1 = path1.replace("@loader_path", join(prefix, dirname(binary)))
                    if exists(abspath(join(prefix, path1))):
                        path = path1
                        break
                else:
                    return "not found"
        path = path.replace("@loader_path", join(prefix, dirname(binary)))
        if path.startswith("/"):
            return abspath(path)
        return "not found"


def test_installable(channel="defaults"):
    success = True
    log = get_logger(__name__)
    has_py = re.compile(r"py(\d)(\d)")
    for platform in ["osx-64", "linux-32", "linux-64", "win-32", "win-64"]:
        log.info("######## Testing platform %s ########", platform)
        channels = [channel]
        index = get_index(channel_urls=channels, prepend=False, platform=platform)
        for _, rec in index.items():
            # If we give channels at the command line, only look at
            # packages from those channels (not defaults).
            if channel != "defaults" and rec.get("schannel", "defaults") == "defaults":
                continue
            name = rec["name"]
            if name in {"conda", "conda-build"}:
                # conda can only be installed in the root environment
                continue
            if name.endswith("@"):
                # this is a 'virtual' feature record that conda adds to the index for the solver
                # and should be ignored here
                continue
            # Don't fail just because the package is a different version of Python
            # than the default.  We should probably check depends rather than the
            # build string.
            build = rec["build"]
            match = has_py.search(build)
            assert match if "py" in build else True, build
            if match:
                additional_packages = [f"python={match.group(1)}.{match.group(2)}"]
            else:
                additional_packages = []

            version = rec["version"]
            log.info("Testing %s=%s", name, version)

            try:
                install_steps = check_install(
                    [name + "=" + version] + additional_packages,
                    channel_urls=channels,
                    prepend=False,
                    platform=platform,
                )
                success &= bool(install_steps)
            except KeyboardInterrupt:
                raise
            # sys.exit raises an exception that doesn't subclass from Exception
            except BaseException as e:
                success = False
                log.error(
                    "FAIL: %s %s on %s with %s (%s)",
                    name,
                    version,
                    platform,
                    additional_packages,
                    e,
                )
    return success


def _installed(prefix):
    installed = linked_data(prefix)
    installed = {rec["name"]: dist for dist, rec in installed.items()}
    return installed


def _underlined_text(text):
    return str(text) + "\n" + "-" * len(str(text)) + "\n\n"


def inspect_linkages(
    packages,
    prefix=sys.prefix,
    untracked=False,
    all_packages=False,
    show_files=False,
    groupby="package",
    sysroot="",
):
    pkgmap = {}

    installed = _installed(prefix)

    if not packages and not untracked and not all_packages:
        raise ValueError(
            "At least one package or --untracked or --all must be provided"
        )

    if all_packages:
        packages = sorted(installed.keys())

    if untracked:
        packages.append(untracked_package)

    for pkg in ensure_list(packages):
        if pkg == untracked_package:
            dist = untracked_package
        elif pkg not in installed:
            sys.exit(f"Package {pkg} is not installed in {prefix}")
        else:
            dist = installed[pkg]

        if not sys.platform.startswith(("linux", "darwin")):
            sys.exit(
                "Error: conda inspect linkages is only implemented in Linux and OS X"
            )

        if dist == untracked_package:
            obj_files = get_untracked_obj_files(prefix)
        else:
            obj_files = get_package_obj_files(dist, prefix)
        linkages = get_linkages(obj_files, prefix, sysroot)
        depmap = defaultdict(list)
        pkgmap[pkg] = depmap
        depmap["not found"] = []
        depmap["system"] = []
        for binary in linkages:
            for lib, path in linkages[binary]:
                path = (
                    replace_path(binary, path, prefix)
                    if path not in {"", "not found"}
                    else path
                )
                if path.startswith(prefix):
                    in_prefix_path = re.sub("^" + prefix + "/", "", path)
                    deps = list(which_package(in_prefix_path, prefix))
                    if len(deps) > 1:
                        deps_str = [str(dep) for dep in deps]
                        get_logger(__name__).warn(
                            "Warning: %s comes from multiple " "packages: %s",
                            path,
                            comma_join(deps_str),
                        )
                    if not deps:
                        if exists(path):
                            depmap["untracked"].append(
                                (lib, path.split(prefix + "/", 1)[-1], binary)
                            )
                        else:
                            depmap["not found"].append(
                                (lib, path.split(prefix + "/", 1)[-1], binary)
                            )
                    for d in deps:
                        depmap[d].append((lib, path.split(prefix + "/", 1)[-1], binary))
                elif path == "not found":
                    depmap["not found"].append((lib, path, binary))
                else:
                    depmap["system"].append((lib, path, binary))

    output_string = ""
    if groupby == "package":
        for pkg in packages:
            output_string += _underlined_text(pkg)
            output_string += print_linkages(pkgmap[pkg], show_files=show_files)

    elif groupby == "dependency":
        # {pkg: {dep: [files]}} -> {dep: {pkg: [files]}}
        inverted_map = defaultdict(lambda: defaultdict(list))
        for pkg in pkgmap:
            for dep in pkgmap[pkg]:
                if pkgmap[pkg][dep]:
                    inverted_map[dep][pkg] = pkgmap[pkg][dep]

        # print system and not found last
        k = sorted(set(inverted_map.keys()) - {"system", "not found"})
        for dep in k + ["system", "not found"]:
            output_string += _underlined_text(dep)
            output_string += print_linkages(inverted_map[dep], show_files=show_files)

    else:
        raise ValueError("Unrecognized groupby: %s" % groupby)
    if hasattr(output_string, "decode"):
        output_string = output_string.decode("utf-8")
    return output_string


def inspect_objects(packages, prefix=sys.prefix, groupby="package"):
    installed = _installed(prefix)

    output_string = ""
    for pkg in ensure_list(packages):
        if pkg == untracked_package:
            dist = untracked_package
        elif pkg not in installed:
            raise ValueError(f"Package {pkg} is not installed in {prefix}")
        else:
            dist = installed[pkg]

        output_string += _underlined_text(pkg)

        if not sys.platform.startswith("darwin"):
            sys.exit("Error: conda inspect objects is only implemented in OS X")

        if dist == untracked_package:
            obj_files = get_untracked_obj_files(prefix)
        else:
            obj_files = get_package_obj_files(dist, prefix)

        info = []
        for f in obj_files:
            f_info = {}
            path = join(prefix, f)
            filetype = codefile_type(path)
            if filetype == "machofile":
                f_info["filetype"] = human_filetype(path, None)
                f_info["rpath"] = ":".join(get_rpaths(path))
                f_info["filename"] = f
                info.append(f_info)

        output_string += print_object_info(info, groupby)
    if hasattr(output_string, "decode"):
        output_string = output_string.decode("utf-8")
    return output_string


def get_hash_input(packages):
    hash_inputs = {}
    for pkg in ensure_list(packages):
        pkgname = os.path.basename(pkg)[:-8]
        hash_inputs[pkgname] = {}
        hash_input = package_has_file(pkg, "info/hash_input.json")
        if hash_input:
            hash_inputs[pkgname]["recipe"] = json.loads(hash_input)
        else:
            hash_inputs[pkgname] = "<no hash_input.json in file>"

    return hash_inputs
