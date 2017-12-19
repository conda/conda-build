from __future__ import absolute_import, division, print_function

import os
import sys
from os.path import isfile, join, expanduser

from conda_build.conda_interface import root_dir


def find_executable(executable, prefix=None):
    # dir_paths is referenced as a module-level variable
    #  in other code
    global dir_paths
    if sys.platform == 'win32':
        dir_paths = [join(root_dir, 'Scripts'),
                     join(root_dir, 'Library\\mingw-w64\\bin'),
                     join(root_dir, 'Library\\usr\\bin'),
                     join(root_dir, 'Library\\bin'), ]
        if prefix:
            dir_paths[0:0] = [join(prefix, 'Scripts'),
                         join(prefix, 'Library\\mingw-w64\\bin'),
                         join(prefix, 'Library\\usr\\bin'),
                         join(prefix, 'Library\\bin'), ]
    else:
        dir_paths = [join(root_dir, 'bin'), ]
        if prefix:
            dir_paths.insert(0, join(prefix, 'bin'))

    dir_paths.extend(os.environ['PATH'].split(os.pathsep))

    for dir_path in dir_paths:
        if sys.platform == 'win32':
            for ext in '.exe', '.bat', '':
                path = join(dir_path, executable + ext)
                if isfile(path):
                    return path
        else:
            path = join(dir_path, executable)
            exp_path = expanduser(path)
            if isfile(exp_path) and os.access(exp_path, os.X_OK):
                return expanduser(path)
