# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import importlib
import logging
import os
import pkgutil
import sys

from conda_build.conda_interface import ArgumentParser

import conda_build.api as api
from conda_build.config import Config
from conda_build.cli.main_build import args_func

thisdir = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(level=logging.INFO)


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

    skeletons = [name for _, name, _ in
                 pkgutil.iter_modules([os.path.join(thisdir, '../skeletons')])]
    for skeleton in skeletons:
        if skeleton.startswith("_"):
            continue
        module = importlib.import_module("conda_build.skeletons." + skeleton)
        module.add_parser(repos)

    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p, Config(**args.__dict__))


def execute(args, parser, config):
    if not args.repo:
        parser.print_help()
        sys.exit()

    for package in args.packages:
        api.skeletonize(package, repo=args.repo, config=config)


if __name__ == '__main__':
    main()
