# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import sys
import argparse
from os.path import abspath
from collections import defaultdict

from conda.misc import which_package
from conda.lock import Locked

from conda_build.main_build import args_func
from conda_build.config import config
from conda_build.ldd import get_package_linkages

def main():
    p = argparse.ArgumentParser(
        description='tool for inspecting conda packages'
    )

    subcommand = p.add_subparsers(
        dest='subcommand',
        )
    linkages = subcommand.add_parser(
        "linkages",
        help="Tools to investigate linkages of binary libraries in a package",
        )
    linkages.add_argument(
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

def print_linkages(depmap):
    # Print system and not found last
    k = sorted(depmap.keys() - {'system', 'not found'})
    for dep in k + ['system', 'not found']:
        print("%s:" % dep)
        for lib, path in sorted(depmap[dep]):
            print("    %s (%s)" % (lib, path))
        print()

def execute(args, parser):
    with Locked(config.croot):
        for pkg in args.packages:
            if args.subcommand == 'linkages':
                linkages = get_package_linkages(pkg)
                depmap = defaultdict(set)
                for binary in linkages:
                    for lib, path in linkages[binary]:
                        path = abspath(path) if path not in {'', 'not found'} else path
                        if path.startswith(config.test_prefix):
                            deps = list(which_package(path))
                            if len(deps) > 1:
                                print("Warning: %s comes from multiple packages: %s" % (path, ' and '.join(deps)), file=sys.stderr)
                            for d in deps:
                                depmap[d].add((lib,
                                    path.split(config.test_prefix + '/', 1)[-1]))
                        elif path == 'not found':
                            depmap['not found'].add((lib, path))
                        else:
                            depmap['system'].add((lib, path))

                print_linkages(depmap)
