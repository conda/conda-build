import argparse
import sys
import conda_build.api as api
from attrdict import AttrDict
from conda_build.config import Config


def parse_args(args):
    p = argparse.ArgumentParser()
    p.description = """
Tool for initializing a new python project. It takes care of setting up git, github, travisci,
versioning, setup.py, and more."""
    subparsers = p.add_subparsers(dest="command")
    init_p = subparsers.add_parser("cut")
    init_p.add_argument('name', metavar='PROJECT_NAME',
                   help='name of project')
    init_p.add_argument('path', metavar='PROJECT_PATH',
                   help='path where the project will be created')
    args = p.parse_args(args)
    return p, args


def execute(args):
    parser, args = parse_args(args)
    config = AttrDict(args.__dict__)
    if args.command == 'cut':
        api.cut_project(config.name, config.path, config)
    else:
        parser.print_help()
        raise ValueError("Unknown command: {}".format(args.command))


def main():
    execute(sys.argv[1:])
