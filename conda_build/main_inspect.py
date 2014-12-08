# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import sys
import argparse
from os.path import realpath, expanduser, abspath
from collections import defaultdict
from operator import itemgetter

from conda.misc import which_package
from conda.lock import Locked
from conda.cli.common import add_parser_prefix, get_prefix
import conda.install as ci

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
    linkages.add_argument(
        '--show-files',
        action="store_true",
        help="Show the files in the package that link to each library",
    )
    add_parser_prefix(linkages)
    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)

def print_linkages(depmap, show_files=False):
    # Print system and not found last
    k = sorted(depmap.keys() - {'system', 'not found'})
    for dep in k + ['system', 'not found']:
        print("%s:" % dep)
        if show_files:
            for lib, path, binary in sorted(depmap[dep]):
                print("    %s (%s) from %s" % (lib, path, binary))
        else:
            for lib, path in sorted(set(map(itemgetter(0, 1), depmap[dep]))):
                print("    %s (%s)" % (lib, path))
        print()

def execute(args, parser):
    if not args.subcommand:
        parser.print_help()
    with Locked(config.croot):
        if args.subcommand == 'linkages':
            if not sys.platform.startswith('linux'):
                sys.exit("Error: conda inspect linkages is only implemented in Linux")

            prefix = get_prefix(args)
            installed = ci.linked(prefix)
            for pkg in args.packages:
                for dist in installed:
                    if pkg == dist.rsplit('-', 2)[0]:
                        break
                else:
                    sys.exit("Package %s is not installed in %s" % (pkg, prefix))
                linkages = get_package_linkages(dist, prefix)
                depmap = defaultdict(list)
                for binary in linkages:
                    for lib, path in linkages[binary]:
                        path = abspath(path) if path not in {'', 'not found'} else path
                        if path.startswith(config.test_prefix):
                            deps = list(which_package(path))
                            if len(deps) > 1:
                                print("Warning: %s comes from multiple packages: %s" % (path, ' and '.join(deps)), file=sys.stderr)
                            for d in deps:
                                depmap[d].append((lib,
                                    path.split(config.test_prefix + '/',
                                        1)[-1], binary))
                        elif path == 'not found':
                            depmap['not found'].append((lib, path, binary))
                        else:
                            depmap['system'].append((lib, path, binary))

                print_linkages(depmap, show_files=args.show_files)
