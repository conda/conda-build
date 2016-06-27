# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import sys
from os.path import join, isdir, abspath, expanduser, exists
import shutil

from conda.cli.common import add_parser_prefix, get_prefix
from conda.cli.conda_argparse import ArgumentParser
from conda_build.cli.main_build import args_func
from conda_build.post import mk_relative_osx
from conda_build.utils import _check_call, rec_glob

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
        metavar='PATH',
        nargs='+',
        help="Path to the source directory."
    )
    p.add_argument('-npf', '--no-pth-file',
                   action='store_true',
                   help=("Relink compiled extension dependencies against "
                         "libraries found in current conda env. "
                         "Do not add source to conda.pth."))
    p.add_argument('-b', '--build_ext',
                   action='store_true',
                   help=("Build extensions inplace, invoking: "
                         "python setup.py build_ext --inplace; "
                         "add to conda.pth; relink runtime libraries to "
                         "environment's lib/."))
    p.add_argument('-c', '--clean',
                   action='store_true',
                   help=("Invoke clean on setup.py: "
                         "python setup.py clean "
                         "use with build_ext to clean before building."))
    p.add_argument('-u', '--uninstall',
                   action='store_true',
                   help=("Removes package if installed in 'development mode' "
                         "by deleting path from conda.pth file. Ignore other "
                         "options - just uninstall and exit"))

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
        name, ver, _ = package .rsplit('-', 2)
        if name == 'python':
            py_ver = ver[:3]  # x.y
            break
    else:
        raise RuntimeError("python is not installed in %s" % prefix)

    # current environment's site-packages directory
    sp_dir = get_site_pkg(prefix, py_ver)

    for path in args.source:
        pkg_path = abspath(expanduser(path))

        if args.uninstall:
            # uninstall then exit - does not do any other operations
            uninstall(sp_dir, pkg_path)
            sys.exit(0)

        if args.clean or args.build_ext:
            setup_py = get_setup_py(pkg_path)
            if args.clean:
                clean(setup_py)
                if not args.build_ext:
                    sys.exit(0)

            # build extensions before adding to conda.pth
            if args.build_ext:
                build_ext(setup_py)

        if not args.no_pth_file:
            write_to_conda_pth(sp_dir, pkg_path)

        # go through the source looking for compiled extensions and make sure
        # they use the conda environment for loading libraries at runtime
        relink_sharedobjects(pkg_path, prefix)
        print("completed operation for: " + pkg_path)

if __name__ == '__main__':
    main()
