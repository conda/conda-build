from __future__ import absolute_import, division, print_function

import os
import sys
from os.path import isfile, join, expanduser

from conda_build.conda_interface import cc


def find_executable(executable, prefix=None):
    # dir_paths is referenced as a module-level variable
    #  in other code
    global dir_paths
    if sys.platform == 'win32':
        dir_paths = [join(cc.root_dir, 'Scripts'),
                     join(cc.root_dir, 'Library\\mingw-w64\\bin'),
                     join(cc.root_dir, 'Library\\usr\\bin'),
                     join(cc.root_dir, 'Library\\bin'), ]
        if prefix:
            dir_paths = [join(prefix, 'Scripts'),
                         join(prefix, 'Library\\mingw-w64\\bin'),
                         join(prefix, 'Library\\usr\\bin'),
                         join(prefix, 'Library\\bin'), ] + dir_paths
    else:
        dir_paths = [join(cc.root_dir, 'bin'), ]
        if prefix:
            dir_paths = [join(prefix, 'bin'), ] + dir_paths

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
