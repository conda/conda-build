# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import json
import pprint
import re
import sys
import os
import tarfile
from locale import getpreferredencoding
from os.path import abspath, expanduser, isdir, join, split

from conda.compat import PY3
from conda.cli.conda_argparse import ArgumentParser
from conda_build.main_build import args_func

from conda_build.convert import (has_cext, tar_update, get_pure_py_file_map,
                                 has_nonpy_entry_points)


epilog = """

Tool to convert packages

conda convert converts pure Python packages to other platforms, and converts
Gohlke's .exe packages into conda packages.

Packages are automatically organized in subdirectories according to platform,
e.g.,

osx-64/
  package-1.0-py33.tar.bz2
win-32/
  package-1.0-py33.tar.bz2

Examples:

Convert a package built with conda build to Windows 64-bit, and place the
resulting package in the current directory (supposing a default Anaconda
install on Mac OS X):

    conda convert package-1.0-py33.tar.bz2 -p win-64

Convert a Gohlke .exe to a conda package, and add make it depend on numpy 1.8
or higher:

    conda convert cvxopt-1.1.7.win-amd64-py2.7.exe -d 'numpy >=1.8'

"""


def main():
    p = ArgumentParser(
        description="""
Various tools to convert conda packages. Takes a pure Python package build for
one platform and converts it to work on one or more other platforms, or
all.""" ,
        epilog=epilog,
    )

    # TODO: Factor this into a subcommand, since it's python package specific
    p.add_argument(
        'package_files',
        metavar='package-files',
        action="store",
        nargs='+',
        help="Package files to convert."
    )
    p.add_argument(
        '-p', "--platform",
        dest='platforms',
        action="append",
        choices=['osx-64', 'linux-32', 'linux-64', 'win-32', 'win-64', 'all'],
        help="Platform to convert the packages to."
    )
    p.add_argument(
        "--dependencies", "-d",
        nargs='*',
        help="""Additional (besides python) dependencies of the converted
        package.  To specify a version restriction for a dependency, wrap
        the dependency in quotes, like 'package >=2.0'.""",
    )
    p.add_argument(
        '--show-imports',
        action='store_true',
        default=False,
        help="Show Python imports for compiled parts of the package.",
    )
    p.add_argument(
        '-f', "--force",
        action="store_true",
        help="Force convert, even when a package has compiled C extensions.",
    )
    p.add_argument(
        '-o', '--output-dir',
        default='.',
        help="""Directory to write the output files. The packages will be
        organized in platform/ subdirectories, e.g.,
        win-32/package-1.0-py27_0.tar.bz2."""
    )
    p.add_argument(
        '-v', '--verbose',
        default=False,
        action='store_true',
        help="Print verbose output."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Only display what would have been done.",
    )
    p.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Don't print as much output."
    )

    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)


path_mapping = [# (unix, windows)
                ('lib/python{pyver}', 'Lib'),
                ('bin', 'Scripts')]

pyver_re = re.compile(r'python\s+(\d.\d)')


def conda_convert(file, args):
    if not args.show_imports and args.platforms is None:
        sys.exit('Error: --platform option required for conda package conversion')

    with tarfile.open(file) as t:
        if args.show_imports:
            has_cext(t, show=True)
            return

        if not args.force and has_cext(t, show=args.show_imports):
            print("WARNING: Package %s has C extensions, skipping. Use -f to "
                  "force conversion." % file, file=sys.stderr)
            return

        file_dir, fn = split(file)

        info = json.loads(t.extractfile('info/index.json')
                          .read().decode('utf-8'))
        source_type = 'unix' if info['platform'] in {'osx', 'linux'} else 'win'

        nonpy_unix = False
        nonpy_win = False

        if 'all' in args.platforms:
            args.platforms = ['osx-64', 'linux-32', 'linux-64', 'win-32', 'win-64']
        for platform in args.platforms:
            output_dir = join(args.output_dir, platform)
            if abspath(expanduser(join(output_dir, fn))) == file:
                if not args.quiet:
                    print("Skipping %s/%s. Same as input file" % (platform, fn))
                continue
            if not PY3:
                platform = platform.decode('utf-8')
            dest_plat = platform.split('-')[0]
            dest_type = 'unix' if dest_plat in {'osx', 'linux'} else 'win'

            if source_type == 'unix' and dest_type == 'win':
                nonpy_unix = nonpy_unix or has_nonpy_entry_points(t,
                    unix_to_win=True,
                    show=args.verbose,
                    quiet=args.quiet)
            if source_type == 'win' and dest_type == 'unix':
                nonpy_win = nonpy_win or has_nonpy_entry_points(t,
                    unix_to_win=False,
                    show=args.verbose,
                    quiet=args.quiet)

            if nonpy_unix and not args.force:
                print(("WARNING: Package %s has non-Python entry points, "
                       "skipping %s to %s conversion. Use -f to force.") %
                      (file, info['platform'], platform), file=sys.stderr)
                continue

            if nonpy_win and not args.force:
                print(("WARNING: Package %s has entry points, which are not "
                       "supported yet. Skipping %s to %s conversion. Use -f to force.") %
                      (file, info['platform'], platform), file=sys.stderr)
                continue

            file_map = get_pure_py_file_map(t, platform)

            if args.dry_run:
                if not args.quiet:
                    print("Would convert %s from %s to %s" %
                        (file, info['platform'], dest_plat))
                if args.verbose:
                    pprint.pprint(file_map)
                continue
            else:
                if not args.quiet:
                    print("Converting %s from %s to %s" %
                        (file, info['platform'], platform))

            if not isdir(output_dir):
                os.makedirs(output_dir)
            tar_update(t, join(output_dir, fn), file_map,
                verbose=args.verbose, quiet=args.quiet)


def execute(args, parser):
    files = args.package_files

    for file in files:
        # Don't use byte literals for paths in Python 2
        if not PY3:
            file = file.decode(getpreferredencoding())

        file = abspath(expanduser(file))
        if file.endswith('.tar.bz2'):
            conda_convert(file, args)

        elif file.endswith('.exe'):
            from conda_build.convert_gohlke import convert

            if args.platforms:
                raise RuntimeError('--platform option not allowed for Gohlke '
                                   '.exe package conversion')
            convert(file, args.output_dir, add_depends=args.dependencies,
                    verbose=args.verbose)

        elif file.endswith('.whl'):
            raise RuntimeError('Conversion from wheel packages is not '
                               'implemented yet, stay tuned.')

        else:
            raise RuntimeError("cannot convert: %s" % file)


if __name__ == '__main__':
    main()
