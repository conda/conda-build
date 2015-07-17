# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import sys
from os.path import join, isdir, abspath, expanduser
from os import walk
import fnmatch

from conda.cli.common import add_parser_prefix, get_prefix
from conda.cli.conda_argparse import ArgumentParser
from conda_build.main_build import args_func
from conda_build.post import mk_relative_osx

from conda.install import linked


def main():
    p = ArgumentParser(
        description="""

Install a Python package in 'development mode'.

This works by creating a conda.pth file in site-packages."""
        # TODO: Use setup.py to determine any entry-points to install.
    )

    p.add_argument(
        'source',
        action="store",
        metavar='PATH',
        nargs='+',
        help="Path to the source directory."
    )
    p.add_argument(
                   '-npf', '--no-pth-file',
                   action='store_true',
                   help=("Relink compiled extension dependencies against "
                         "libraries found in current conda env. "
                         "Do not add source to conda.pth."))
    add_parser_prefix(p)
    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)


def sharedobjects_list(pkg_path):
    '''
    return list of shared objects (*.so) found in pkg_path.

    :param pkg_path: look for shared objects to relink in pkg_path
    '''
    bin_files = []

    # only relevant for mac/linux
    pattern = '*.so'

    for d_f in walk(pkg_path):
        m = fnmatch.filter(d_f[2], pattern)
        if m:
            # list is not empty, append full path to binary, then add it
            # to bin_files list
            bin_files.extend([join(d_f[0], f) for f in m])

    return bin_files


def relink_sharedobjects(pkg_path, build_prefix):
    '''
    invokes functions in post module to relink to libraries in conda env

    :param pkg_path: look for shared objects to relink in pkg_path
    :param build_prefix: path to conda environment which contains lib/. to find
        runtime libraries.

    .. note:: develop mode builds the extensions in place and makes a link to
        package in site-packages/. The build_prefix points to conda environment
        since runtime libraries should be loaded from environment's lib/. first
    '''
    # find binaries in package dir and make them relocatable
    bin_files = sharedobjects_list(pkg_path)
    for b_file in bin_files:
        if sys.platform == 'darwin':
            mk_relative_osx(b_file, build_prefix)
        else:
            print("Nothing to do on Linux or Windows.")


def write_to_conda_pth(sp_dir, pkg_path):
    '''
    append pkg_path to conda.pth in site-packages directory for current
    environment

    :param sp_dir: path to site-packages/. directory
    :param pkg_path: the package path to append to site-packes/. dir.
    '''
    with open(join(sp_dir, 'conda.pth'), 'a') as f:
        f.write(pkg_path + '\n')
        print("added " + pkg_path)


def execute(args, parser):
    prefix = get_prefix(args)
    if not isdir(prefix):
        sys.exit("""\
Error: environment does not exist: %s
#
# Use 'conda create' to create the environment first.
#""" % prefix)
    for package in linked(prefix):
        name, ver, _ = package .rsplit('-', 2)
        if name == 'python':
            py_ver = ver[:3] # x.y
            break
    else:
        raise RuntimeError("python is not installed in %s" % prefix)

    for path in args.source:
        pkg_path = abspath(expanduser(path))
        if not args.no_pth_file:
            stdlib_dir = join(prefix, 'Lib' if sys.platform == 'win32' else
                              'lib/python%s' % py_ver)
            sp_dir = join(stdlib_dir, 'site-packages')

            # todo:
            # build the package if setup.py is found then invoke it with
            # build_ext --inplace - this only exists for extensions

            write_to_conda_pth(sp_dir, pkg_path)

        # go through the source looking for compiled extensions and make sure
        # they use the conda environment for loading libraries at runtime
        relink_sharedobjects(pkg_path, prefix)
        print("completed operation for: " + pkg_path)

if __name__ == '__main__':
    main()
