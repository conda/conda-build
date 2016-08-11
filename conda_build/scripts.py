'''
Module for creating entry points and scripts for PyPI packages.
'''

from __future__ import absolute_import, division, print_function

import re
import os
import sys
from os.path import dirname, isdir, join

from .conda_interface import linked
from .conda_interface import cc
from conda_build.utils import copy_into


PY_TMPL = """\
if __name__ == '__main__':
    import sys
    import %(module)s

    sys.exit(%(module)s.%(func)s())
"""

bin_dirname = 'Scripts' if sys.platform == 'win32' else 'bin'

entry_pat = re.compile('\s*([\w\-\.]+)\s*=\s*([\w.]+):([\w.]+)\s*$')


def iter_entry_points(items):
    for item in items:
        m = entry_pat.match(item)
        if m is None:
            sys.exit("Error cound not match entry point: %r" % item)
        yield m.groups()


def create_entry_point(path, module, func, config):
    pyscript = PY_TMPL % {'module': module, 'func': func}
    if sys.platform == 'win32':
        with open(path + '-script.py', 'w') as fo:
            packages = linked(config.build_prefix)
            packages_names = (pkg.split('-')[0] for pkg in packages)
            if 'debug' in packages_names:
                fo.write('#!python_d\n')
            fo.write(pyscript)
        copy_into(join(dirname(__file__), 'cli-%d.exe' % cc.bits), path + '.exe', config)
    else:
        with open(path, 'w') as fo:
            fo.write('#!%s\n' % config.build_python)
            fo.write(pyscript)
        os.chmod(path, int('755', 8))


def create_entry_points(items, config):
    if not items:
        return
    bin_dir = join(config.build_prefix, bin_dirname)
    if not isdir(bin_dir):
        os.mkdir(bin_dir)
    for cmd, module, func in iter_entry_points(items):
        create_entry_point(join(bin_dir, cmd), module, func, config)


def prepend_bin_path(env, prefix, prepend_prefix=False):
    # bin_dirname takes care of bin on *nix, Scripts on win
    env['PATH'] = join(prefix, bin_dirname) + os.pathsep + env['PATH']
    if sys.platform == "win32":
        env['PATH'] = join(prefix, "Library", "mingw-w64", "bin") + os.pathsep + \
                      join(prefix, "Library", "usr", "bin") + os.pathsep + os.pathsep + \
                      join(prefix, "Library", "bin") + os.pathsep + \
                      env['PATH']
        prepend_prefix = True  # windows has Python in the prefix.  Use it.
    if prepend_prefix:
        env['PATH'] = prefix + os.pathsep + env['PATH']
    return env
