# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import argparse

from conda.lock import Locked

from conda_build.main_build import args_func
from conda_build.config import config
from conda_build.ldd import get_package_linkages

def main():
    p = argparse.ArgumentParser(
        description='tool for inspecting conda packages'
    )

    p.add_argument(
        'packages',
        action='store',
        nargs='+',
        help='conda packages to inspect',
    )
    p.add_argument(
        '--linkages',
        action="store_true",
        help="inspect the linkages of the binary files in the package",
    )
    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)

def execute(args, parser):
    with Locked(config.croot):
        for pkg in args.packages:
            if args.linkages:
                linkages = get_package_linkages(pkg)
                print(linkages)
