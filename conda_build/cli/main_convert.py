# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from locale import getpreferredencoding
import logging
from os.path import abspath, expanduser
import sys

from conda_build.conda_interface import ArgumentParser

from conda_build import api
from conda_build.utils import PY3

logging.basicConfig(level=logging.INFO)

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


def parse_args(args):
    p = ArgumentParser(
        description="""
Various tools to convert conda packages. Takes a pure Python package build for
one platform and converts it to work on one or more other platforms, or
all.""",
        epilog=epilog,
    )

    # TODO: Factor this into a subcommand, since it's python package specific
    p.add_argument(
        'files',
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

    args = p.parse_args(args)
    return p, args


def execute(args):
    parser, args = parse_args(args)
    files = args.files
    del args.__dict__['files']

    for f in files:
        # Don't use byte literals for paths in Python 2
        if not PY3:
            f = f.decode(getpreferredencoding())

        f = abspath(expanduser(f))
        api.convert(f, **args.__dict__)


def main():
    return execute(sys.argv[1:])
