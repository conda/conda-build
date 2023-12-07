# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache
from os.path import basename
from pathlib import Path
from typing import Iterable

from conda.models.records import PrefixRecord

from conda_build.conda_interface import untracked
from conda_build.os_utils.macho import otool
from conda_build.os_utils.pyldd import codefile_class, inspect_linkages, machofile

from ..deprecations import deprecated
from ..utils import on_linux, on_mac

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


def get_linkages(
    obj_files: Iterable[str],
    prefix: str | os.PathLike | Path,
    sysroot,
) -> dict[str, list[tuple[str, str]]]:
    return _get_linkages(tuple(obj_files), Path(prefix), sysroot)


@lru_cache(maxsize=None)
def _get_linkages(
    obj_files: tuple[str],
    prefix: Path,
    sysroot,
) -> dict[str, list[tuple[str, str]]]:
    linkages = {}
    for file in obj_files:
        # Detect the filetype to emulate what the system-native tool does.
        path = prefix / file
        if codefile_class(path) == machofile:
            resolve_filenames = False
            recurse = False
        else:
            resolve_filenames = True
            recurse = True
        ldd_emulate = [
            (basename(link), link)
            for link in inspect_linkages(
                path,
                resolve_filenames=resolve_filenames,
                sysroot=sysroot,
                recurse=recurse,
            )
        ]

        try:
            if on_linux:
                ldd_computed = ldd(path)
            elif on_mac:
                ldd_computed = [
                    (basename(link["name"]), link["name"]) for link in otool(path)
                ]
        except:
            # ldd quite often fails on foreign architectures, fallback to
            ldd_computed = ldd_emulate

        if set(ldd_computed) != set(ldd_emulate):
            print("WARNING: pyldd disagrees with ldd/otool. This will not cause any")
            print("WARNING: problems for this build, but please file a bug at:")
            print("WARNING: https://github.com/conda/conda-build")
            print(f"WARNING: and (if possible) attach file {path}")
            print("WARNING:")
            print("  ldd/otool gives:")
            print("    " + "\n    ".join(map(str, ldd_computed)))
            print("  pyldd gives:")
            print("    " + "\n    ".join(map(str, ldd_emulate)))
            print(f"Diffs\n{set(ldd_computed) - set(ldd_emulate)}")
            print(f"Diffs\n{set(ldd_emulate) - set(ldd_computed)}")

        linkages[file] = ldd_computed
    return linkages


@deprecated("3.28.0", "24.1.0")
@lru_cache(maxsize=None)
def get_package_files(
    prec: PrefixRecord, prefix: str | os.PathLike | Path
) -> list[str]:
    return prec["files"]


@lru_cache(maxsize=None)
def get_package_obj_files(
    prec: PrefixRecord, prefix: str | os.PathLike | Path
) -> list[str]:
    return [file for file in prec["files"] if codefile_class(Path(prefix, file))]


@lru_cache(maxsize=None)
def get_untracked_obj_files(prefix: str | os.PathLike | Path) -> list[str]:
    return [
        file for file in untracked(str(prefix)) if codefile_class(Path(prefix, file))
    ]
