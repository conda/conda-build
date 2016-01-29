# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import sys
import re
import os
from os.path import abspath, join, dirname, exists, basename
from collections import defaultdict
from operator import itemgetter

from conda.misc import which_package
from conda.cli.common import add_parser_prefix, get_prefix, InstalledPackages
from conda.cli.conda_argparse import ArgumentParser
import conda.install as ci

from conda.api import get_index
from conda.cli.install import check_install
from conda.config import get_default_urls, normalize_urls

from conda_build.main_build import args_func
from conda_build.ldd import get_linkages, get_package_obj_files, get_untracked_obj_files
from conda_build.macho import get_rpaths, human_filetype
from conda_build.utils import groupby, getter, comma_join

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
    ).completer=InstalledPackages
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
        '--groupby',
        action='store',
        default='package',
        choices=('package', 'dependency'),
        help="""Attribute to group by (default: %(default)s). Useful when used
        in conjunction with --all.""",
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
    ).completer=InstalledPackages
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

    channels_help = """
Tools for investigating conda channels.
"""
    channels = subcommand.add_parser(
        "channels",
        help=channels_help,
        description=channels_help,
        )
    channels.add_argument(
        '--verbose',
        action='store_true',
        help="""Show verbose output. Note that error output to stderr will
        always be shown regardless of this flag. """,
        )
    channels.add_argument(
        '--test-installable', '-t',
        action='store_true',
        help="""Test every package in the channel to see if it is installable
        by conda.""",
    )
    channels.add_argument(
        "channel",
        nargs='?',
        default="defaults",
        help="The channel to test. The default is %(default)s."
        )

    p.set_defaults(func=execute)
    args = p.parse_args()
    args_func(args, p)

def print_linkages(depmap, show_files=False):
    # Print system and not found last
    k = sorted(set(depmap.keys()) - {'system', 'not found'})
    all_deps = k if 'not found' not in depmap.keys() else k + ['system', 'not found']
    for dep in all_deps:
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
        if path == basename(binary):
            return abspath(join(prefix, binary))
        if '@rpath' in path:
            rpaths = get_rpaths(join(prefix, binary))
            if not rpaths:
                return "NO LC_RPATH FOUND"
            else:
                for rpath in rpaths:
                    path1 = path.replace("@rpath", rpath)
                    path1 = path1.replace('@loader_path', join(prefix, dirname(binary)))
                    if exists(abspath(join(prefix, path1))):
                        path = path1
                        break
                else:
                    return 'not found'
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

def test_installable(channel='defaults', verbose=True):
    if not verbose:
        sys.stdout = open(os.devnull, 'w')

    success = False
    has_py = re.compile(r'py(\d)(\d)')
    for platform in ['osx-64', 'linux-32', 'linux-64', 'win-32', 'win-64']:
        print("######## Testing platform %s ########" % platform)
        channels = [channel] + get_default_urls()
        index = get_index(channel_urls=channels, prepend=False, platform=platform)
        for package in sorted(index):
            if channel != 'defaults':
                # If we give channels at the command line, only look at
                # packages from those channels (not defaults).
                if index[package]['channel'] not in normalize_urls([channel], platform=platform):
                    continue
            name, version, build = package.rsplit('.tar.bz2', 1)[0].rsplit('-', 2)
            if name in {'conda', 'conda-build'}:
                # conda can only be installed in the root environment
                continue
            # Don't fail just because the package is a different version of Python
            # than the default.  We should probably check depends rather than the
            # build string.
            match = has_py.search(build)
            assert match if 'py' in build else True, build
            if match:
                additional_packages = ['python=%s.%s' % (match.group(1), match.group(2))]
            else:
                additional_packages = []

            print('Testing %s=%s' % (name, version))
            # if additional_packages:
            #     print("Including %s" % additional_packages[0])

            try:
                check_install([name + '=' + version] + additional_packages,
                    channel_urls=channels, prepend=False,
                    platform=platform)
            except KeyboardInterrupt:
                raise
            # sys.exit raises an exception that doesn't subclass from Exception
            except BaseException as e:
                success = True
                print("FAIL: %s %s on %s with %s (%s)" % (name, version,
                    platform, additional_packages, e), file=sys.stderr)

    return success

def execute(args, parser):
    if not args.subcommand:
        parser.print_help()
        exit()

    if args.subcommand == 'channels':
        if not args.test_installable:
            parser.error("At least one option (--test-installable) is required.")
        else:
            sys.exit(not test_installable(channel=args.channel, verbose=args.verbose))

    prefix = get_prefix(args)
    installed = ci.linked(prefix)

    if not args.packages and not args.untracked and not args.all:
        parser.error("At least one package or --untracked or --all must be provided")

    if args.all:
        args.packages = sorted([i.rsplit('-', 2)[0] for i in installed])

    if args.untracked:
        args.packages.append(untracked_package)


    if args.subcommand == 'linkages':
        pkgmap = {}
        for pkg in args.packages:
            if pkg == untracked_package:
                dist = untracked_package
            else:
                for dist in installed:
                    if pkg == dist.rsplit('-', 2)[0]:
                        break
                else:
                    sys.exit("Package %s is not installed in %s" % (pkg, prefix))

            if not sys.platform.startswith(('linux', 'darwin')):
                sys.exit("Error: conda inspect linkages is only implemented in Linux and OS X")

            if dist == untracked_package:
                obj_files = get_untracked_obj_files(prefix)
            else:
                obj_files = get_package_obj_files(dist, prefix)
            linkages = get_linkages(obj_files, prefix)
            depmap = defaultdict(list)
            pkgmap[pkg] = depmap
            depmap['not found'] = []
            for binary in linkages:
                for lib, path in linkages[binary]:
                    path = replace_path(binary, path, prefix) if path not in {'', 'not found'} else path
                    if path.startswith(prefix):
                        deps = list(which_package(path))
                        if len(deps) > 1:
                            print("Warning: %s comes from multiple packages: %s" % (path, comma_join(deps)), file=sys.stderr)
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

        if args.groupby == 'package':
            for pkg in args.packages:
                print(pkg)
                print('-'*len(str(pkg)))
                print()

                print_linkages(pkgmap[pkg], show_files=args.show_files)
        elif args.groupby == 'dependency':
            # {pkg: {dep: [files]}} -> {dep: {pkg: [files]}}
            inverted_map = defaultdict(lambda: defaultdict(list))
            for pkg in pkgmap:
                for dep in pkgmap[pkg]:
                    if pkgmap[pkg][dep]:
                        inverted_map[dep][pkg] = pkgmap[pkg][dep]

            # print system and not found last
            k = sorted(set(inverted_map.keys()) - {'system', 'not found'})
            for dep in k + ['system', 'not found']:
                print(dep)
                print('-'*len(str(dep)))
                print()

                print_linkages(inverted_map[dep], show_files=args.show_files)

        else:
            raise ValueError("Unrecognized groupby: %s" % args.groupby)

    if args.subcommand == 'objects':
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
                f_info['rpath'] = ':'.join(get_rpaths(path))
                f_info['filename'] = f
                info.append(f_info)

            print_object_info(info, args.groupby)
