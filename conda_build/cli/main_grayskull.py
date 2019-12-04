import importlib
import logging

from conda_build.conda_interface import ArgumentParser

logging.basicConfig(level=logging.INFO)


def parse_args(args):
    parser = ArgumentParser(
        description="""
Generates a boilerplate/skeleton recipe, which you can then edit to create a
full recipe. Some simple skeleton recipes may not even need edits.
        """,
        epilog="""
Run --help on the subcommands like 'conda skeleton pypi --help' to see the
options available.
        """,
    )

    repos = parser.add_subparsers(dest="repo")
    module = importlib.import_module("conda_build.grayskull.pypi")
    module.add_parser(repos)

    args = parser.parse_args(args)
    return parser, args
