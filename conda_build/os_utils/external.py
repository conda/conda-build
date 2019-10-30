from __future__ import absolute_import, division, print_function

import os
import stat
import sys
from os.path import isfile, join, expanduser

from conda_build.conda_interface import root_dir
from glob2 import glob


def find_executable(executable, prefix=None):
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
        dir_paths = [join(root_dir, "bin")]
        if prefix:
            dir_paths.insert(0, join(prefix, "bin"))

    dir_paths.extend(os.environ["PATH"].split(os.pathsep))
    if sys.platform == "win32":
        exts = (".exe", ".bat", "")
    else:
        exts = ("",)

    for dir_path in dir_paths:
        for ext in exts:
            path = expanduser(join(dir_path, executable + ext))
            if isfile(path):
                st = os.stat(path)
                if sys.platform == "win32" or st.st_mode & stat.S_IEXEC:
                    result = path
                    break
        if not result and any([f in executable for f in ("*", "?", ".")]):
            matches = glob(os.path.join(dir_path, executable))
            if matches:
                result = matches[0]
                break
        if result:
            break
    return result


def find_preferably_prefixed_executable(executable, build_prefix=None):
    found = find_executable("*" + executable, build_prefix)
    if not found:
        found = find_executable(executable, build_prefix)
    return found
