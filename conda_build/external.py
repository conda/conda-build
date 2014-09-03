from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import os
import sys
from os.path import isfile, join, expanduser

import conda.config as cc
from conda_build.config import config

def get_dir_paths():
    dir_paths = None
    if sys.platform == 'win32':
        dir_paths = [join(config.build_prefix, 'Scripts'),
                     join(cc.root_dir, 'Scripts'),
                     'C:\\cygwin\\bin']
    else:
        dir_paths = [join(config.build_prefix, 'bin'),
                     join(cc.root_dir, 'bin'),]

    dir_paths.extend(os.environ['PATH'].split(os.pathsep))
    return dir_paths

def find_executable(executable):

    dir_paths = get_dir_paths()

    for dir_path in dir_paths:
        if sys.platform == 'win32':
            for ext in  '.exe', '.bat', '':
                path = join(dir_path, executable + ext)
                if isfile(path):
                    return path
        else:
            path = join(dir_path, executable)
            if isfile(expanduser(path)):
                return expanduser(path)
    return None
