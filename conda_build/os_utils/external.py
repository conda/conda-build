# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import stat
import sys
from glob import glob
from os.path import expanduser, isfile, join

from conda_build.conda_interface import root_dir


def find_executable(executable, prefix=None, all_matches=False):
    # dir_paths is referenced as a module-level variable
    #  in other code
    global dir_paths
    result = None
    if sys.platform == "win32":
        dir_paths = [
            join(root_dir, "Scripts"),
            join(root_dir, "Library\\mingw-w64\\bin"),
            join(root_dir, "Library\\usr\\bin"),
            join(root_dir, "Library\\bin"),
        ]
        if prefix:
            dir_paths[0:0] = [
                join(prefix, "Scripts"),
                join(prefix, "Library\\mingw-w64\\bin"),
                join(prefix, "Library\\usr\\bin"),
                join(prefix, "Library\\bin"),
            ]
    else:
        dir_paths = [
            join(root_dir, "bin"),
        ]
        if prefix:
            dir_paths.insert(0, join(prefix, "bin"))

    dir_paths.extend(os.environ["PATH"].split(os.pathsep))
    if sys.platform == "win32":
        exts = (".exe", ".bat", "")
    else:
        exts = ("",)

    all_matches_found = []
    for dir_path in dir_paths:
        for ext in exts:
            path = expanduser(join(dir_path, executable + ext))
            if isfile(path):
                st = os.stat(path)
                if sys.platform == "win32" or st.st_mode & stat.S_IEXEC:
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
