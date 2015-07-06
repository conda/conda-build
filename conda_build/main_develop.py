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
                   '-l', '--post-link',
                   action='store_true',
                   help=("Look in source dir for compiled extensions and "
                         "ensure they link against libraries found in conda "
                         "env"))
    add_parser_prefix(p)
    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)


def sharedobjects_list(pkg_path):
    '''
    return list of shared objects (*.so) found in package that was built in
    develop mode. These are located in source directory.
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


def relink_sharedobjects(pkg_path):
    '''
    invokes functions in post module to relink to libraries in conda env

    .. todo: implmenent/test call to mk_relative_linux for linux relinking.

    .. note:: would be good to reuse post.post_build() or post.mk_relative()
        but they require MetaData object which requires conda recipe: meta.yaml
        Currently, develop mode doesn't use meta.yaml
    '''
    # find binaries in package dir and make them relocatable
    bin_files = sharedobjects_list(pkg_path)
    for b_file in bin_files:
        if sys.platform.startswith('linux'):
            # mk_relative_linux(f, rpaths=m.get_value('build/rpaths', ['lib']))
            raise NotImplementedError("unclear what to do for this on linux")
        elif sys.platform == 'darwin':
            mk_relative_osx(b_file, develop=True)


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
        if not args.post_link:
            # build the package if setup.py is found then 
            stdlib_dir = join(prefix, 'Lib' if sys.platform == 'win32' else
                              'lib/python%s' % py_ver)
            sp_dir = join(stdlib_dir, 'site-packages')
            with open(join(sp_dir, 'conda.pth'), 'a') as f:
                for path in args.source:
                    f.write(pkg_path + '\n')
                    print("added " + pkg_path)

        # go through the source looking for compiled extensions and make sure
        # they use the conda build environment for loading libraries at runtime
        relink_sharedobjects(pkg_path)
        print("completed operation for: " + pkg_path)

if __name__ == '__main__':
    main()
