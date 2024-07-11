# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import annotations

import os
import stat
from glob import glob
from os.path import expanduser, isfile, join

from conda.base.context import context

from ..deprecations import deprecated
from ..utils import on_win

_DIR_PATHS: list[str] = []
deprecated.constant("24.7", "24.9", "dir_paths", _DIR_PATHS)


def find_executable(executable, prefix=None, all_matches=False):
    # dir_paths is referenced as a module-level variable
    #  in other code
    global _DIR_PATHS
    result = None
    if on_win:
        _DIR_PATHS = [
            join(context.root_prefix, "Scripts"),
            join(context.root_prefix, "Library\\mingw-w64\\bin"),
            join(context.root_prefix, "Library\\usr\\bin"),
            join(context.root_prefix, "Library\\bin"),
        ]
        if prefix:
            _DIR_PATHS[0:0] = [
                join(prefix, "Scripts"),
                join(prefix, "Library\\mingw-w64\\bin"),
                join(prefix, "Library\\usr\\bin"),
                join(prefix, "Library\\bin"),
            ]
    else:
        _DIR_PATHS = [
            join(context.root_prefix, "bin"),
        ]
        if prefix:
            _DIR_PATHS.insert(0, join(prefix, "bin"))

    _DIR_PATHS.extend(os.environ["PATH"].split(os.pathsep))
    if on_win:
        exts = (".exe", ".bat", "")
    else:
        exts = ("",)

    all_matches_found = []
    for dir_path in _DIR_PATHS:
        for ext in exts:
            path = expanduser(join(dir_path, executable + ext))
            if isfile(path):
                st = os.stat(path)
                if on_win or st.st_mode & stat.S_IEXEC:
                    if all_matches:
                        all_matches_found.append(path)
                    else:
                        result = path
                        break
        if not result and any([f in executable for f in ("*", "?", ".")]):
            matches = glob(os.path.join(dir_path, executable), recursive=True)
            if matches:
                if all_matches:
                    all_matches_found.extend(matches)
                else:
                    result = matches[0]
                    break
        if result:
            break
    return result or all_matches_found


def find_preferably_prefixed_executable(
    executable, build_prefix=None, all_matches=False
):
    found = find_executable("*" + executable, build_prefix, all_matches)
    if not found:
        # It is possible to force non-prefixed exes by passing os.sep as the
        # first character in executable. basename makes this work.
        found = find_executable(os.path.basename(executable), build_prefix)
    return found
