# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import argparse
import sys
from glob import glob
from locale import getpreferredencoding
from os.path import exists

import conda.config as config
from conda.compat import PY3

from conda_build import __version__


def main():
    p = argparse.ArgumentParser(
        description='''tool for building conda metapackages. A metapackage is a
    package with no files, only metadata'''
    )

    p.add_argument(
        "--no-binstar-upload",
        action="store_false",
        help="do not ask to upload the package to binstar",
        dest='binstar_upload',
        default=config.binstar_upload,
    )
    p.add_argument(
        "--output",
        action="store_true",
        help="output the conda package filename which would have been "
               "created and exit",
    )
    p.add_argument(
        "pkg-name",
        action="store",
        help="name of the created package",
    )
    p.add_argument(
        "pkg-version",
        action="store",
        help="version of the created package",
    )
    p.add_argument(
        "--build-number",
        action="store",
        type=int,
        default=0,
        help="build number for the package (default is 0)",
    )
    p.add_argument(
        "--build-string",
        action="store",
        default=None,
        help="build string for the package (default is automatically generated)",
    )
    p.add_argument(
        "--dependencies", "-d",
        nargs='*',
        help="""The dependencies of the package. To specify a version
        restriction for a dependency, wrap the dependency in quotes, like
        'package >=2.0'""",
    )
    p.set_defaults(func=execute)

    args = p.parse_args()
    args.func(args, p)


def execute(args, parser):
    pass
