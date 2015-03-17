# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import sys
import argparse
from os.path import abspath, join, dirname, exists
from collections import defaultdict
from operator import itemgetter

from conda.misc import which_package
from conda.cli.common import add_parser_prefix, get_prefix
import conda.install as ci

from conda_build.main_build import args_func
from conda_build.ldd import get_linkages, get_package_obj_files, get_untracked_obj_files
from conda_build.macho import get_rpath, human_filetype

def main():
    p = argparse.ArgumentParser(
        description='Tools for inspecting conda packages'
    )
    subcommand = p.add_subparsers(
        dest='subcommand',
        )

    linkages = subcommand.add_parser(
        "linkages",
        help="""Investigate linkages of binary libraries in a package
        (only works in Linux and OS X)""",
        )
    linkages.add_argument(
        'packages',
        action='store',
        nargs='*',
        help='conda packages to inspect',
    )
    linkages.add_argument(
        '--untracked',
        action='store_true',
        help="""Inspect the untracked files in the environment. Useful when used
        in conjunction with conda build --build-only.""",
    )
    linkages.add_argument(
        '--show-files',
        action="store_true",
        help="Show the files in the package that link to each library",
    )
    add_parser_prefix(linkages)

    objects = subcommand.add_parser(
        "objects",
        help="""Investigate binary object files in a package (only works in OS
        X)""",
        )
    objects.add_argument(
        'packages',
        action='store',
        nargs='*',
        help='conda packages to inspect',
    )
    objects.add_argument(
        '--untracked',
        action='store_true',
        help="""Inspect the untracked files in the environment. Useful when used
        in conjunction with conda build --build-only.""",
    )
    objects.add_argument(
        '--groupby',
        action='store',
        default='filename',
        choices={'filename', 'filetype', 'rpath'},
        help='Attribute to group by (default: %(default)s)',
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
            rpath = get_rpath(path)
            if not rpath:
                return "NO LC_RPATH FOUND"
            else:
                path = path.replace("@rpath", rpath)
        path = path.replace('@loader_path', join(prefix, dirname(binary)))
        if path.startswith('/'):
            return abspath(path)
        return 'not found'

def print_object_info(info, key):
    printed = set()
    for f in sorted(info):
        if info[f][key] not in printed:
            print(info[f][key])
            printed.add(info[f][key])
        for data in sorted(info[f]):
            if data == key:
                continue
            if info[f][data] is None:
                continue
            print('  %s: %s' % (data, info[f][data]))
        print()

def execute(args, parser):
    if not args.subcommand:
        parser.print_help()

    prefix = get_prefix(args)
    installed = ci.linked(prefix)

    untracked_package = object()

    if not args.packages and not args.untracked:
        parser.error("At least one package or --untracked must be provided")

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
            info = defaultdict(dict)

            for f in obj_files:
                path = join(prefix, f)
                info[f]['filetype'] = human_filetype(path)
                info[f]['rpath'] = get_rpath(path)
                info[f]['filename'] = f

            print_object_info(info, args.groupby)
