# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys
import argparse
from locale import getpreferredencoding

import conda.config as config
from conda.compat import PY3

from conda_build import __version__


def main():
    p = argparse.ArgumentParser(
        description='tool for building conda packages'
    )

    p.add_argument(
        '-c', "--check",
        action="store_true",
        help="only check (validate) the recipe",
    )
    p.add_argument(
        "--no-binstar-upload",
        action="store_false",
        help="do not ask to upload the package to binstar",
        dest='binstar_upload',
        default=config.binstar_upload,
    )
    p.add_argument(
        "--output",
        action="store_true",
        help="output the conda package filename which would have been "
               "created and exit",
    )
    p.add_argument(
        '-s', "--source",
        action="store_true",
        help="only obtain the source (but don't build)",
    )
    p.add_argument(
        '-t', "--test",
        action="store_true",
        help="test package (assumes package is already build)",
    )
    p.add_argument(
        'recipe',
        action="store",
        metavar='PATH',
        nargs='+',
        help="path to recipe directory"
    )
    p.add_argument(
        '--no-test',
        action='store_true',
        dest='notest',
        help="do not test the package"
    )
    p.add_argument(
        '-V', '--version',
        action='version',
        version = 'conda-build %s' % __version__,
    )
    p.set_defaults(func=execute)

    args = p.parse_args()
    args.func(args, p)


def handle_binstar_upload(path, args):
    import subprocess
    from conda_build.external import find_executable

    if args.binstar_upload is None:
        args.yes = False
        args.dry_run = False
#        upload = common.confirm_yn(
#            args,
#            message="Do you want to upload this "
#            "package to binstar", default='yes', exit_no=False)
        upload = False
    else:
        upload = args.binstar_upload

    no_upload_message = """\
# If you want to upload this package to binstar.org later, type:
#
# $ binstar upload %s
#
# To have conda build upload to binstar automatically, use
# $ conda config --set binstar_upload yes
""" % path
    if not upload:
        print(no_upload_message)
        return

    binstar = find_executable('binstar')
    if binstar is None:
        print(no_upload_message)
        sys.exit('''
Error: cannot locate binstar (required for upload)
# Try:
# $ conda install binstar
''')
    print("Uploading to binstar")
    args = [binstar, 'upload', path]
    if config.binstar_personal:
        args += ['--personal']
    try:
        subprocess.call(args)
    except:
        print(no_upload_message)
        raise


def check_external():
    import os
    import conda_build.external as external

    if sys.platform.startswith('linux'):
        patchelf = external.find_executable('patchelf')
        if patchelf is None:
            sys.exit("""\
Error:
    Did not find 'patchelf' in: %s
    'patchelf' is necessary for building conda packages on Linux with
    relocatable ELF libraries.  You can install patchelf using apt-get,
    yum or conda.
""" % (os.pathsep.join(external.dir_paths)))


def execute(args, parser):
    import sys
    import shutil
    import tarfile
    import tempfile
    from os.path import abspath, isdir, isfile, join

    from conda.lock import Locked
    import conda_build.build as build
    import conda_build.source as source
    from conda_build.config import croot
    from conda_build.metadata import MetaData

    check_external()

    with Locked(croot):
        for arg in args.recipe:
            # Don't use byte literals for paths in Python 2
            if not PY3:
                arg = arg.decode(getpreferredencoding())
            if isfile(arg):
                if arg.endswith(('.tar', '.tar.gz', '.tgz', '.tar.bz2')):
                    recipe_dir = tempfile.mkdtemp()
                    t = tarfile.open(arg, 'r:*')
                    t.extractall(path=recipe_dir)
                    t.close()
                    need_cleanup = True
                else:
                    print("Ignoring non-recipe: %s" % arg)
                    continue
            else:
                recipe_dir = abspath(arg)
                need_cleanup = False

            if not isdir(recipe_dir):
                sys.exit("Error: no such directory: %s" % recipe_dir)

            m = MetaData(recipe_dir)
            binstar_upload = False
            if args.check and len(args.recipe) > 1:
                print(m.path)
            m.check_fields()
            if args.check:
                continue
            if args.output:
                print(build.bldpkg_path(m))
                continue
            elif args.test:
                build.test(m)
            elif args.source:
                source.provide(m.path, m.get_section('source'))
                print('Source tree in:', source.get_dir())
            else:
                build.build(m)
                if not args.notest:
                    build.test(m)
                binstar_upload = True

            if need_cleanup:
                shutil.rmtree(recipe_dir)

            if binstar_upload:
                handle_binstar_upload(build.bldpkg_path(m), args)


if __name__ == '__main__':
    main()
