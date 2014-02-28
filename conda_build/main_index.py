from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import os
from os.path import abspath
from optparse import OptionParser

from conda_build.index import update_index


def main():
    p = OptionParser(
        usage="usage: %prog [options] DIR [DIR ...]",
        description="display useful information about tar files")

    p.add_option('-f', "--force",
                 action = "store_true",
                 help = "force reading all files")

    p.add_option('-q', "--quiet",
                 action = "store_true")

    opts, args = p.parse_args()

    if len(args) == 0:
        dir_paths = [os.getcwd()]
    else:
        dir_paths = [abspath(path) for path in args]

    for path in dir_paths:
        update_index(path, verbose=not opts.quiet, force=opts.force)


if __name__ == '__main__':
    main()
