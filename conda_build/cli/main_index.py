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
        "-n", "--channel-name",
        help="Customize the channel name listed in each channel's index.html.",
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
    p.add_argument(
        "--hotfix-source-repo",
        help="URL of git repo that hosts your metadata patch instructions"
    )
    p.add_argument(
        "--verbose", help="show extra debugging info", action="store_true"
    )
    p.add_argument(
        "--no-progress", help="Hide progress bars", action="store_false", dest="progress"
    )
    p.add_argument(
        "--no-shared-format-cache", action="store_false", dest="shared_format_cache",
        help=("Do not share a cache between .tar.bz2 and .conda files.  By default, "
              "we assume that two files that differ only by extension can be treated "
              "as similar for the purposes of caching metadata.  This flag disables that assumption.")
    )

    args = p.parse_args(args)
    return p, args


def execute(args):
    _, args = parse_args(args)
    api.update_index(args.dir, check_md5=args.check_md5, channel_name=args.channel_name,
                     threads=args.threads, subdir=args.subdir, patch_generator=args.patch_generator,
                     verbose=args.verbose, progress=args.progress, hotfix_source_repo=args.hotfix_source_repo,
                     shared_format_cache=args.shared_format_cache)


def main():
    return execute(sys.argv[1:])
