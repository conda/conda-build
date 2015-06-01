# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import sys
from os.path import abspath, join, dirname, exists
from collections import defaultdict
from operator import itemgetter

from conda.misc import which_package
from conda.cli.common import add_parser_prefix, get_prefix
from conda.cli.conda_argparse import ArgumentParser
import conda.install as ci

from conda_build.main_build import args_func
from conda_build.ldd import get_linkages, get_package_obj_files, get_untracked_obj_files
from conda_build.macho import get_rpath, human_filetype
from conda_build.utils import groupby, getter

def main():
    p = ArgumentParser(
        description='Tools for inspecting conda packages.',
        epilog="""
Run --help on the subcommands like 'conda inspect linkages --help' to see the
options available.
        """,

    )
    subcommand = p.add_subparsers(
        dest='subcommand',
    )

    linkages_help = """
Investigates linkages of binary libraries in a package (works in Linux and
OS X). This is an advanced command to aid building packages that link against
C libraries. Aggregates the output of ldd (on Linux) and otool -L (on OS X) by
dependent packages. Useful for finding broken links, or links against system
libraries that ought to be dependent conda packages.  """
    linkages = subcommand.add_parser(
        "linkages",
        # help controls conda inspect -h and description controls conda
        # inspect linkages -h
        help=linkages_help,
        description=linkages_help,
        )
    linkages.add_argument(
        'packages',
        action='store',
        nargs='*',
        help='Conda packages to inspect.',
    )
    linkages.add_argument(
        '--untracked',
        action='store_true',
        help="""Inspect the untracked files in the environment. This is useful when used in
        conjunction with conda build --build-only.""",
    )
    linkages.add_argument(
        '--show-files',
        action="store_true",
        help="Show the files in the package that link to each library",
    )
    linkages.add_argument(
        '--all',
        action='store_true',
        help="Generate a report for all packages in the environment.",
    )
    add_parser_prefix(linkages)

    objects_help = """
Investigate binary object files in a package (only works on OS X). This is an
advanced command to aid building packages that have compiled
libraries. Aggregates the output of otool on all the binary object files in a
package.
"""
    objects = subcommand.add_parser(
        "objects",
        help=objects_help,
        description=objects_help,
        )
    objects.add_argument(
        'packages',
        action='store',
        nargs='*',
        help='Conda packages to inspect.',
    )
    objects.add_argument(
        '--untracked',
        action='store_true',
        help="""Inspect the untracked files in the environment. This is useful when used
        in conjunction with conda build --build-only.""",
    )
    # TODO: Allow groupby to include the package (like for --all)
    objects.add_argument(
        '--groupby',
        action='store',
        default='filename',
        choices=('filename', 'filetype', 'rpath'),
        help='Attribute to group by (default: %(default)s).',
    )
    objects.add_argument(
        '--all',
        action='store_true',
        help="Generate a report for all packages in the environment.",
    )
    add_parser_prefix(objects)

    p.set_defaults(func=execute)
    args = p.parse_args()
    args_func(args, p)

def print_linkages(depmap, show_files=False):
    # Print system and not found last
    k = sorted(set(depmap.keys()) - {'system', 'not found'})
    for dep in k + ['system', 'not found']:
        print("%s:" % dep)
        if show_files:
            for lib, path, binary in sorted(depmap[dep]):
                print("    %s (%s) from %s" % (lib, path, binary))
        else:
            for lib, path in sorted(set(map(itemgetter(0, 1), depmap[dep]))):
                print("    %s (%s)" % (lib, path))
        print()

def replace_path(binary, path, prefix):
    if sys.platform.startswith('linux'):
        return abspath(path)
    elif sys.platform.startswith('darwin'):
        if '@rpath' in path:
            rpath = get_rpath(join(prefix, binary))
            if not rpath:
                return "NO LC_RPATH FOUND"
            else:
                path = path.replace("@rpath", rpath)
        path = path.replace('@loader_path', join(prefix, dirname(binary)))
        if path.startswith('/'):
            return abspath(path)
        return 'not found'

def print_object_info(info, key):
    gb = groupby(key, info)
    for header in sorted(gb, key=str):
        print(header)
        for f_info in sorted(gb[header], key=getter('filename')):
            for data in sorted(f_info):
                if data == key:
                    continue
                if f_info[data] is None:
                    continue
                print('  %s: %s' % (data, f_info[data]))
            if len([i for i in f_info if f_info[i] is not None and i != key]) > 1:
                print()
        print()

class _untracked_package:
    def __str__(self):
        return "<untracked>"

untracked_package = _untracked_package()

def execute(args, parser):
    if not args.subcommand:
        parser.print_help()

    prefix = get_prefix(args)
    installed = ci.linked(prefix)

    if not args.packages and not args.untracked and not args.all:
        parser.error("At least one package or --untracked or --all must be provided")

    if args.all:
        args.packages = sorted([i.rsplit('-', 2)[0] for i in installed])

    if args.untracked:
        args.packages.append(untracked_package)

    for pkg in args.packages:
        if pkg == untracked_package:
            dist = untracked_package
        else:
            for dist in installed:
                if pkg == dist.rsplit('-', 2)[0]:
                    break
            else:
                sys.exit("Package %s is not installed in %s" % (pkg, prefix))

        print(pkg)
        print('-'*len(str(pkg)))
        print()

        if args.subcommand == 'linkages':
            if not sys.platform.startswith(('linux', 'darwin')):
                sys.exit("Error: conda inspect linkages is only implemented in Linux and OS X")

            if dist == untracked_package:
                obj_files = get_untracked_obj_files(prefix)
            else:
                obj_files = get_package_obj_files(dist, prefix)
            linkages = get_linkages(obj_files, prefix)
            depmap = defaultdict(list)
            for binary in linkages:
                for lib, path in linkages[binary]:
                    path = replace_path(binary, path, prefix) if path not in {'', 'not found'} else path
                    if path.startswith(prefix):
                        deps = list(which_package(path))
                        if len(deps) > 1:
                            print("Warning: %s comes from multiple packages: %s" % (path, ' and '.join(deps)), file=sys.stderr)
                        if not deps:
                            if exists(path):
                                depmap['untracked'].append((lib, path.split(prefix
                                    + '/', 1)[-1], binary))
                            else:
                                depmap['not found'].append((lib, path.split(prefix
                                    + '/', 1)[-1], binary))
                        for d in deps:
                            depmap[d].append((lib, path.split(prefix + '/',
                                1)[-1], binary))
                    elif path == 'not found':
                        depmap['not found'].append((lib, path, binary))
                    else:
                        depmap['system'].append((lib, path, binary))

            print_linkages(depmap, show_files=args.show_files)

        if args.subcommand == 'objects':
            if not sys.platform.startswith('darwin'):
                sys.exit("Error: conda inspect objects is only implemented in OS X")

            if dist == untracked_package:
                obj_files = get_untracked_obj_files(prefix)
            else:
                obj_files = get_package_obj_files(dist, prefix)

            info = []
            for f in obj_files:
                f_info = {}
                path = join(prefix, f)
                f_info['filetype'] = human_filetype(path)
                f_info['rpath'] = get_rpath(path)
                f_info['filename'] = f
                info.append(f_info)

            print_object_info(info, args.groupby)
