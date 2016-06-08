# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

from conda.cli.conda_argparse import ArgumentParser
from conda.lock import Locked

import conda_build.api as api
from conda_build.config import config
from conda_build.main_build import args_func

import importlib
import pkgutil


def main():
    p = ArgumentParser(
        description="""
Generates a boilerplate/skeleton recipe, which you can then edit to create a
full recipe. Some simple skeleton recipes may not even need edits.
        """,
        epilog="""
Run --help on the subcommands like 'conda skeleton pypi --help' to see the
options available.
        """,
    )

    repos = p.add_subparsers(
        dest="repo"
    )

    skeletons = [name for _, name, _ in pkgutil.iter_modules(['conda_build/skeletons'])]
    for skeleton in skeletons:
        module = importlib.import_module("conda_build.skeletons." + skeleton)
        module.add_parser(repos)

    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)


def execute(args, parser):

    if not args.repo:
        parser.print_help()
        sys.exit()

    for package in packages:
        api.skeletonize(args.packages, args.repo, **args)

    except ImportError:
        sys.exit("No support for module: " + args.repo)
    with Locked(config.croot):
        module.main(args, parser)


if __name__ == '__main__':
    main()
