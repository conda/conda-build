# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import re
import subprocess
import sys
from functools import lru_cache
from os.path import basename, join

from conda_build.conda_interface import linked_data, untracked
from conda_build.os_utils.macho import otool
from conda_build.os_utils.pyldd import (
    codefile_class,
    inspect_linkages,
    is_codefile,
    machofile,
)

LDD_RE = re.compile(r"\s*(.*?)\s*=>\s*(.*?)\s*\(.*\)")
LDD_NOT_FOUND_RE = re.compile(r"\s*(.*?)\s*=>\s*not found")


def ldd(path):
    "thin wrapper around ldd"
    lines = subprocess.check_output(["ldd", path]).decode("utf-8").splitlines()
    res = []
    for line in lines:
        if "=>" not in line:
            continue

        assert line[0] == "\t", (path, line)
        m = LDD_RE.match(line)
        if m:
            res.append(m.groups())
            continue
        m = LDD_NOT_FOUND_RE.match(line)
        if m:
            res.append((m.group(1), "not found"))
            continue
        if "ld-linux" in line:
            continue
        raise RuntimeError("Unexpected output from ldd: %s" % line)

    return res


def get_linkages(obj_files, prefix, sysroot):
    return _get_linkages(tuple(obj_files), prefix, sysroot)


@lru_cache(maxsize=None)
def _get_linkages(obj_files, prefix, sysroot):
    res = {}

    for f in obj_files:
        path = join(prefix, f)
        # ldd quite often fails on foreign architectures.
        ldd_failed = False
        # Detect the filetype to emulate what the system-native tool does.
        klass = codefile_class(path)
        if klass == machofile:
            resolve_filenames = False
            recurse = False
        else:
            resolve_filenames = True
            recurse = True
        try:
            if sys.platform.startswith("linux"):
                res[f] = ldd(path)
            elif sys.platform.startswith("darwin"):
                links = otool(path)
                res[f] = [(basename(line["name"]), line["name"]) for line in links]
        except:
            ldd_failed = True
        finally:
            res_py = inspect_linkages(
                path,
                resolve_filenames=resolve_filenames,
                sysroot=sysroot,
                recurse=recurse,
            )
            res_py = [(basename(lp), lp) for lp in res_py]
            if ldd_failed:
                res[f] = res_py
            else:
                if set(res[f]) != set(res_py):
                    print(
                        "WARNING: pyldd disagrees with ldd/otool. This will not cause any"
                    )
                    print("WARNING: problems for this build, but please file a bug at:")
                    print("WARNING: https://github.com/conda/conda-build")
                    print(f"WARNING: and (if possible) attach file {path}")
                    print(
                        "WARNING: \nldd/otool gives:\n{}\npyldd gives:\n{}\n".format(
                            "\n".join(str(e) for e in res[f]),
                            "\n".join(str(e) for e in res_py),
                        )
                    )
                    print(f"Diffs\n{set(res[f]) - set(res_py)}")
                    print(f"Diffs\n{set(res_py) - set(res[f])}")
    return res


@lru_cache(maxsize=None)
def get_package_files(dist, prefix):
    files = []
    if hasattr(dist, "get"):
        files = dist.get("files")
    else:
        data = linked_data(prefix).get(dist)
        if data:
            files = data.get("files", [])
    return files


@lru_cache(maxsize=None)
def get_package_obj_files(dist, prefix):
    res = []
    files = get_package_files(dist, prefix)
    for f in files:
        path = join(prefix, f)
        if is_codefile(path):
            res.append(f)

    return res


@lru_cache(maxsize=None)
def get_untracked_obj_files(prefix):
    res = []
    files = untracked(prefix)
    for f in files:
        path = join(prefix, f)
        if is_codefile(path):
            res.append(f)

    return res
