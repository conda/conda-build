from __future__ import absolute_import, division, print_function

import os
import sys
from os.path import isfile, join, expanduser

from .conda_interface import root_dir
from conda_build.config import config


def find_executable(executable):
    # dir_paths is referenced as a module-level variable
    #  in other code
    global dir_paths
    if sys.platform == 'win32':
        dir_paths = [join(config.build_prefix, 'Scripts'),
                     join(config.build_prefix, 'Library\\mingw-w64\\bin'),
                     join(config.build_prefix, 'Library\\usr\\bin'),
                     join(config.build_prefix, 'Library\\bin'),
                     join(root_dir, 'Scripts'),
                     join(root_dir, 'Library\\mingw-w64\\bin'),
                     join(root_dir, 'Library\\usr\\bin'),
                     join(root_dir, 'Library\\bin'), ]
    else:
        dir_paths = [join(config.build_prefix, 'bin'),
                     join(root_dir, 'bin'), ]

    dir_paths.extend(os.environ['PATH'].split(os.pathsep))

    for dir_path in dir_paths:
        if sys.platform == 'win32':
            for ext in '.exe', '.bat', '':
                path = join(dir_path, executable + ext)
                if isfile(path):
                    return path
        else:
            path = join(dir_path, executable)
            if isfile(expanduser(path)):
                return expanduser(path)
    return None
