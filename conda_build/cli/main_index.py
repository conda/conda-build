from __future__ import absolute_import, division, print_function

import logging
import os
import sys

from conda_build.conda_interface import ArgumentParser

from conda_build import api
from conda_build.index import DEFAULT_SUBDIRS, MAX_THREADS_DEFAULT

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
        help="""Use hash values instead of file modification times for determining if a
        package's metadata needs to be updated.""",
    )
    p.add_argument(
        'channel_name',
        help='Adding a channel name will create an index.html file within the subdir.',
        nargs='?',
        default=None,
    )
    p.add_argument(
        '-s', '--subdir',
        action='append',
        help='Optional. The subdir to index. Can be given multiple times. If not provided, will '
             'default to all of %s. If provided, will not create channeldata.json for the channel.'
             '' % ', '.join(DEFAULT_SUBDIRS),
    )
    p.add_argument(
        '-t', '--threads',
        default=MAX_THREADS_DEFAULT,
        type=int,
    )
    p.add_argument(
        "-p", "--patch-generator",
        help="Path to Python file that outputs metadata patch instructions"
    )

    args = p.parse_args(args)
    return p, args


def execute(args):
    _, args = parse_args(args)
    api.update_index(args.dir, check_md5=args.check_md5, channel_name=args.channel_name,
                     threads=args.threads, subdir=args.subdir, patch_generator=args.patch_generator)


def main():
    return execute(sys.argv[1:])
