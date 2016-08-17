from __future__ import absolute_import, division, print_function

import logging
import os
import sys

from conda_build.conda_interface import ArgumentParser

from conda_build import api
from conda_build.config import Config

logging.basicConfig(level=logging.INFO)


def parse_args(args):
    p = ArgumentParser(
        description="Update package index metadata files in given directories.")

    p.add_argument(
        'dir',
        help='Directory that contains an index to be updated.',
        nargs='*',
        default=[os.getcwd()],
    )

    p.add_argument(
        '-c', "--check-md5",
        action="store_true",
        help="""Use MD5 values instead of file modification times for determining if a
        package's metadata needs to be updated.""",
    )

    p.add_argument(
        '-f', "--force",
        action="store_true",
        help="Force reading all files.",
    )

    p.add_argument(
        '-q', "--quiet",
        action="store_true",
        help="Don't show any output.",
    )
    p.add_argument(
        '--no-remove',
        action="store_false",
        dest="remove",
        default=True,
        help="Don't remove entries for files that don't exist.",
    )

    args = p.parse_args(args)
    return p, args


def execute(args):
    p, args = parse_args(args)
    config = Config(**args.__dict__)
    config.verbose = not args.quiet

    api.update_index(args.dir, config=config, force=args.force,
            check_md5=args.check_md5, remove=args.remove)


def main():
    return execute(sys.argv[1:])
