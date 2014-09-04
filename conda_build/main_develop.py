# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import argparse
import sys
from os.path import join, isdir, abspath, expanduser

from conda.cli.common import add_parser_prefix, get_prefix
from conda_build.main_build import args_func

from conda.install import linked

def main():
    p = argparse.ArgumentParser(
        description="""Install a Python package in 'development mode'.

    This works by creating a conda.pth file in site-packages, and using
    setup.py to determine any entry-points to install."""
    )

    p.add_argument(
        'source',
        action="store",
        metavar='PATH',
        nargs='+',
        help="path to the source directory"
    )
    add_parser_prefix(p)
    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)


def execute(args, parser):
    prefix = get_prefix(args)
    if not isdir(prefix):
        sys.exit("""\
Error: environment does not exist: %s
#
# Use 'conda create' to create the environment first.
#""" % prefix)
    for package in linked(prefix):
        name, ver, build = package.rsplit('-', 2)
        if name == 'python':
            py_ver = ver[:3] # x.y
            break
    else:
        raise RuntimeError("python is not installed in %s" % prefix)

    stdlib_dir = join(prefix, 'Lib' if sys.platform == 'win32' else
        'lib/python%s' % py_ver)
    sp_dir = join(stdlib_dir, 'site-packages')
    with open(join(sp_dir, 'conda.pth'), 'a') as f:
        for path in args.source:
            f.write(abspath(expanduser(path)) + '\n')


if __name__ == '__main__':
    main()
