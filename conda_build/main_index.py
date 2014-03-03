from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import argparse
import os
from locale import getpreferredencoding
from os.path import abspath

from conda.compat import PY3

from conda_build.index import update_index


def main():
    p = argparse.ArgumentParser(
        description="Update package index metadata files in given directories")

    p.add_argument('dir',
                   help='Directory that contains an index to be updated.',
                   nargs='*',
                   default=[os.getcwd()])

    p.add_argument('-f', "--force",
                   action="store_true",
                   help="force reading all files")

    p.add_argument('-q', "--quiet",
                   action="store_true")

    args = p.parse_args()

    dir_paths = [abspath(path) for path in args.dir]
    # Don't use byte strings in Python 2
    if not PY3:
        dir_paths = [path.decode(getpreferredencoding()) for path in dir_paths]

    for path in dir_paths:
        update_index(path, verbose=(not args.quiet), force=args.force)


if __name__ == '__main__':
    main()
