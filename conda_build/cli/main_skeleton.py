# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import importlib
import logging
import os
import pkgutil
import sys

from .. import api
from ..conda_interface import ArgumentParser
from ..config import Config
from ..deprecations import deprecated

thisdir = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(level=logging.INFO)


def parse_args(args):
    p = ArgumentParser(
        prog="conda skeleton",
        description="""
Generates a boilerplate/skeleton recipe, which you can then edit to create a
full recipe. Some simple skeleton recipes may not even need edits.
        """,
        epilog="""
Run --help on the subcommands like 'conda skeleton pypi --help' to see the
options available.
        """,
    )

    repos = p.add_subparsers(dest="repo")

    skeletons = [
        name
        for _, name, _ in pkgutil.iter_modules([os.path.join(thisdir, "../skeletons")])
    ]
    for skeleton in skeletons:
        if skeleton.startswith("_"):
            continue
        module = importlib.import_module("conda_build.skeletons." + skeleton)
        module.add_parser(repos)

    args = p.parse_args(args)
    return p, args


def execute(args):
    parser, args = parse_args(args)
    config = Config(**args.__dict__)

    if not args.repo:
        parser.print_help()
        sys.exit()

    api.skeletonize(
        args.packages,
        args.repo,
        output_dir=args.output_dir,
        recursive=args.recursive,
        version=args.version,
        config=config,
    )


@deprecated("3.26.0", "4.0.0", addendum="Use `conda skeleton` instead.")
def main():
    return execute(sys.argv[1:])


if __name__ == "__main__":
    main()
