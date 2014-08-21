# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import argparse
import json
import pprint
import re
import sys
import os
import shutil
import tarfile
import tempfile
import zipfile
from argparse import RawDescriptionHelpFormatter
from locale import getpreferredencoding
from os.path import abspath, basename, dirname, expanduser, isdir, join, split

from conda.compat import PY3
from conda_build.main_build import args_func

from conda_build.convert import (has_cext, tar_update, get_pure_py_file_map,
                                 has_nonpy_entry_points)


epilog = """

For now, it is just a tool to convert pure Python packages to other platforms.

Packages are automatically organized in subdirectories according to platform,
e.g.,

osx-64/
  package-1.0-py33.tar.bz2
win-32/
  package-1.0-py33.tar.bz2

Examples:

Convert a package built with conda build to Windows 64-bit, and place the
resulting package in the current directory (supposing a default Anaconda
install on Mac OS X):

$ conda convert ~/anaconda/conda-bld/osx-64/package-1.0-py33.tar.bz2 -o . -p win-64
"""


def main():
    p = argparse.ArgumentParser(
        description='various tools to convert conda packages',
        epilog=epilog,
        formatter_class=RawDescriptionHelpFormatter,
    )

    # TODO: Factor this into a subcommand, since it's python package specific
    p.add_argument(
        'package_files',
        metavar='package-files',
        action="store",
        nargs='+',
        help="package files to convert"
    )
    p.add_argument(
        '-p', "--platform",
        dest='platforms',
        action="append",
        choices=['osx-64', 'linux-32', 'linux-64', 'win-32', 'win-64', 'all'],
        help="Platform to convert the packages to"
    )
    p.add_argument(
        '--show-imports',
        action='store_true',
        default=False,
        help="Show Python imports for compiled parts of the package",
    )
    p.add_argument(
        '-f', "--force",
        action="store_true",
        help="Force convert, even when a package has compiled C extensions",
    )
    p.add_argument(
        '-o', '--output-dir',
        default='.',
        help="""Directory to write the output files. The packages will be
        organized in platform/ subdirectories, e.g.,
        win-32/package-1.0-py27_0.tar.bz2"""
    )
    p.add_argument(
        '-v', '--verbose',
        default=False,
        action='store_true',
        help="Print verbose output"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="only display what would have been done",
    )

    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)


path_mapping = [# (unix, windows)
                ('lib/python{pyver}', 'Lib'),
                ('bin', 'Scripts')]

pyver_re = re.compile(r'python\s+(\d.\d)')


def conda_convert(file, args):
    if args.platforms is None:
        sys.exit('Error: --platform option required for conda package conversion')

    with tarfile.open(file) as t:
        if not args.force and has_cext(t, show=args.show_imports):
            print("WARNING: Package %s has C extensions, skipping. Use -f to "
                  "force conversion." % file)
            return

        file_dir, fn = split(file)

        info = json.loads(t.extractfile('info/index.json')
                          .read().decode('utf-8'))
        source_type = 'unix' if info['platform'] in {'osx', 'linux'} else 'win'

        nonpy_unix = False
        nonpy_win = False

        if 'all' in args.platforms:
            args.platforms = ['osx-64', 'linux-32', 'linux-64', 'win-32', 'win-64']
        for platform in args.platforms:
            output_dir = join(args.output_dir, platform)
            if abspath(expanduser(join(output_dir, fn))) == file:
                print("Skipping %s/%s. Same as input file" % (platform, fn))
                continue
            if not PY3:
                platform = platform.decode('utf-8')
            dest_plat = platform.split('-')[0]
            dest_type = 'unix' if dest_plat in {'osx', 'linux'} else 'win'

            if source_type == 'unix' and dest_type == 'win':
                nonpy_unix = nonpy_unix or has_nonpy_entry_points(t,
                                                                  unix_to_win=True,
                                                                  show=args.verbose)
            if source_type == 'win' and dest_type == 'unix':
                nonpy_win = nonpy_win or has_nonpy_entry_points(t,
                                                                unix_to_win=False,
                                                                show=args.verbose)

            if nonpy_unix and not args.force:
                print(("WARNING: Package %s has non-Python entry points, "
                       "skipping %s to %s conversion. Use -f to force.") %
                      (file, info['platform'], platform))
                continue

            if nonpy_win and not args.force:
                print(("WARNING: Package %s has entry points, which are not "
                       "supported yet. Skipping %s to %s conversion. Use -f to force.") %
                      (file, info['platform'], platform))
                continue

            file_map = get_pure_py_file_map(t, platform)

            if args.dry_run:
                print("Would convert %s from %s to %s" %
                      (file, info['platform'], dest_plat))
                if args.verbose:
                    pprint.pprint(file_map)
                continue
            else:
                print("Converting %s from %s to %s" %
                      (file, info['platform'], platform))

            if not isdir(output_dir):
                os.makedirs(output_dir)
            tar_update(t, join(output_dir, fn), file_map, verbose=args.verbose)


def gohlke_extract(src_path, dir_path):
    file_map = [
        ('PLATLIB/', 'Lib/site-packages/'),
        ('PURELIB/', 'Lib/site-packages/'),
        ('SCRIPTS/', 'Scripts/'),
        ('DATA/Lib/site-packages/', 'Lib/site-packages/'),
    ]
    z = zipfile.ZipFile(src_path)
    for src in z.namelist():
        if src.endswith(('/', '\\')):
            continue
        for a, b in file_map:
            if src.startswith(a):
                dst = abspath(join(dir_path, b + src[len(a):]))
                break
        else:
            raise RuntimeError("Don't know how to handle file %s" % src)

        dst_dir = dirname(dst)
        #print 'file %r to %r' % (src, dst_dir)
        if not isdir(dst_dir):
            os.makedirs(dst_dir)
        data = z.read(src)
        with open(dst, 'wb') as fi:
            fi.write(data)
    z.close()

def get_files(dir_path):
    res = set()
    for root, dirs, files in os.walk(dir_path):
        for fn in files:
            res.add(join(root, fn)[len(dir_path) + 1:])
    return sorted(res)

def gohlke_convert(file, args):
    if args.platforms:
        sys.exit('Error: --platform not allowed for Gohlke package conversion')
    pat = re.compile(r'([\w\.-]+)-([\w\.]+)\.(win32|win-amd64)-py(\d)\.(\d)\.exe')
    fn1 = basename(file)
    m = pat.match(fn1)
    if m is None:
         print("WARNING: Invalid .exe filename '%s', skipping" % fn1)
         return
    arch_map = {'win32': 'x86', 'win-amd64': 'x86_64'}
    py_ver = '%s.%s' % (m.group(4), m.group(5))
    info = {
        "name": m.group(1).lower(),
        "version": m.group(2),
        "build": "py" + py_ver.replace('.', ''),
        "build_number": 0,
        "depends": ['python %s*' % py_ver],
        "platform": "win",
        "arch": arch_map[m.group(3)],
    }

    tmp_dir = tempfile.mkdtemp()
    gohlke_extract(file, tmp_dir)
    info_dir = join(tmp_dir, 'info')
    os.mkdir(info_dir)
    files = get_files(tmp_dir)
    with open(join(info_dir, 'files'), 'w') as fo:
        for f in files:
            fo.write('%s\n' % f)
    with open(join(info_dir, 'index.json'), 'w') as fo:
        json.dump(info, fo, indent=2, sort_keys=True)
    for fn in os.listdir(info_dir):
        files.append('info/' + fn)

    subdir_map = {'x86': 'win-32', 'x86_64': 'win-64'}
    output_dir = join(args.output_dir, subdir_map[info['arch']])
    if not isdir(output_dir):
        os.makedirs(output_dir)
    fn2 = '%(name)s-%(version)s-%(build)s.tar.bz2' % info
    output_path = join(output_dir, fn2)

    t = tarfile.open(output_path, 'w:bz2')
    for f in files:
        t.add(join(tmp_dir, f), f)
    t.close()

    print("Wrote: %s" % output_path)
    shutil.rmtree(tmp_dir)


def execute(args, parser):
    files = args.package_files

    for file in files:
        # Don't use byte literals for paths in Python 2
        if not PY3:
            file = file.decode(getpreferredencoding())

        file = abspath(expanduser(file))
        if file.endswith('.tar.bz2'):
            conda_convert(file, args)

        elif file.endswith('.exe'):
            gohlke_convert(file, args)

        else:
            raise RuntimeError("cannot convert: %s" % file)


if __name__ == '__main__':
    main()
