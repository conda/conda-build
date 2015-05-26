from __future__ import absolute_import, division, print_function

import os
from locale import getpreferredencoding
from os.path import abspath

from conda.compat import PY3
from conda.cli.conda_argparse import ArgumentParser

from conda_build.index import update_index


def main():
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
        help="Don't remove entries for files that don't exist.,
        )

    args = p.parse_args()

    dir_paths = [abspath(path) for path in args.dir]
    # Don't use byte strings in Python 2
    if not PY3:
        dir_paths = [path.decode(getpreferredencoding()) for path in dir_paths]

    for path in dir_paths:
        update_index(path, verbose=(not args.quiet), force=args.force,
            check_md5=args.check_md5, remove=args.remove)


if __name__ == '__main__':
    main()
