# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

import logging

from conda_build.conda_interface import (ArgumentParser, add_parser_prefix, InstalledPackages,
                                         get_prefix)

from conda_build import api
from conda_build.config import Config
from conda_build.cli.main_build import args_func

logging.basicConfig(level=logging.INFO)


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
    ).completer = InstalledPackages
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
    ).completer = InstalledPackages
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
    config = Config(**args.__dict__)
    args_func(args, p, config=config)


def execute(args, parser, config):
    if not args.subcommand:
        parser.print_help()
        exit()

    elif args.subcommand == 'channels':
        if not args.test_installable:
            parser.error("At least one option (--test-installable) is required.")
        else:
            print(api.test_installable(args.channel))
    elif args.subcommand == 'linkages':
        print(api.inspect_linkages(args.packages, prefix=get_prefix(args),
                                   untracked=args.untracked, all=args.all,
                                   show_files=args.show_files, groupby=args.groupby))
    elif args.subcommand == 'objects':
        print(api.inspect_objects(args.packages, prefix=get_prefix(args), groupby=args.groupby))
    else:
        raise ValueError("Unrecognized subcommand: {0}.".format(args.subcommand))
