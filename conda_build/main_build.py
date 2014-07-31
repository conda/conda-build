# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import argparse
import sys
from collections import deque
from glob import glob
from locale import getpreferredencoding
from os.path import exists

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
        metavar='RECIPE_PATH',
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
        '-b', '--build-only',
        action="store_true",
        help="""only run the build, without any post processing or
        testing. Implies --no-test and --no-binstar-upload""",
    )
    p.add_argument(
        '-p', '--post',
        action="store_true",
        help="run the post-build logic. Implies --no-test and --no-binstar-upload",
    )
    p.add_argument(
        '-V', '--version',
        action='version',
        version = 'conda-build %s' % __version__,
    )
    p.add_argument(
        '-q', "--quiet",
        action="store_true",
        help="do not display progress bar",
    )
    p.add_argument(
        '--python',
        action="append",
        help="Set the python version used by conda build",
    )
    p.add_argument(
        '--perl',
        action="append",
        help="Set the python version used by conda build",
    )
    p.add_argument(
        '--numpy',
        action="append",
        help="Set the python version used by conda build",
    )
    p.add_argument(
        '-I', '--ignore-link-errors',
        action='store_true',
        help=(
            "Ignore any link errors that are detected during post-build "
            "processing (such as linking to libraries outside of the build "
            "prefix, which can cause issues when trying to use the package "
            "on other platforms)"
        )
    )
    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)


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
    binstar_user = config.rc.get('binstar_user', None)
    if binstar_user:
        args = [binstar, 'upload', '--user', binstar_user, path]
    else:
        args = [binstar, 'upload', path]
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
    from os.path import abspath, isdir, isfile

    from conda.lock import Locked
    import conda_build.build as build
    import conda_build.source as source
    import conda_build.config
    from conda_build.config import croot
    from conda_build.metadata import MetaData

    from conda_build.dll import LinkErrors

    check_external()

    if args.python:
        if args.python == ['all']:
            for py in [26, 27, 33, 34]:
                args.python = [str(py)]
                execute(args, parser)
            return
        if len(args.python) > 1:
            for py in args.python[:]:
                args.python = [py]
                execute(args, parser)
        else:
            conda_build.config.CONDA_PY = int(args.python[0].replace('.', ''))
    if args.perl:
        conda_build.config.CONDA_PERL = args.perl
    if args.numpy:
        if args.numpy == ['all']:
            for npy in [16, 17, 18]:
                args.numpy = [str(npy)]
                execute(args, parser)
            return
        if len(args.numpy) > 1:
            for npy in args.numpy[:]:
                args.numpy = [npy]
                execute(args, parser)
        else:
            conda_build.config.CONDA_NPY = int(args.numpy[0].replace('.', ''))

    with Locked(croot):
        recipes = deque(args.recipe)
        while recipes:
            arg = recipes.popleft()
            try_again = False
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
                build.test(m, verbose=not args.quiet)
            elif args.source:
                source.provide(m.path, m.get_section('source'))
                print('Source tree in:', source.get_dir())
            else:
                # This loop recursively builds dependencies if recipes exist
                if args.build_only:
                    post = False
                    args.notest = True
                    args.binstar_upload = False
                elif args.post:
                    post = True
                    args.notest = True
                    args.binstar_upload = False
                else:
                    post = None
                try:
                    build.build(m, verbose=not args.quiet, post=post)
                except build.LinkErrors as e:
                    from conda_build import config
                    ignore_link_errors = args.ignore_link_errors
                    if not ignore_link_errors:
                        ignore_link_errors = config.ignore_link_errors

                    # We always handle link errors.  By default, we use our
                    # simple handler in link.py, however, this can be
                    # customized via the conda config property
                    # 'link_error_handler'.  See conda_build.config for more
                    # info.  Note that we pass the 'ignore_link_errors' as an
                    # argument to the handler -- we don't use it to discern
                    # whether or not to call the handler.
                    handler = config.link_error_handler
                    if not args.ignore_link_errors:
                        print('Ignoring link errors:\n%s\n' % repr(e))
                    else:
                        if handler:
                            h = handler(m, e, recipes)
                            if h.try_again:
                                continue
                        else:
                            raise e
                except RuntimeError as e:
                    error_str = str(e)
                    if error_str.startswith('No packages found matching:'):
                        # Build dependency if recipe exists
                        dep_pkg = error_str.split(': ')[1]
                        # Handle package names that contain version deps.
                        if ' ' in dep_pkg:
                            dep_pkg = dep_pkg.split(' ')[0]
                        recipe_glob = glob(dep_pkg + '-[v0-9][0-9.]*')
                        if exists(dep_pkg):
                            recipe_glob.append(dep_pkg)
                        if recipe_glob:
                            recipes.appendleft(arg)
                            try_again = True
                            for recipe_dir in recipe_glob:
                                print(("Missing dependency {0}, but found" +
                                       " recipe directory, so building " +
                                       "{0} first").format(dep_pkg))
                                recipes.appendleft(recipe_dir)
                        else:
                            raise
                    else:
                        raise
                if try_again:
                    continue

                if not args.notest:
                    build.test(m, verbose=not args.quiet)
                binstar_upload = True

            if need_cleanup:
                shutil.rmtree(recipe_dir)

            if binstar_upload:
                handle_binstar_upload(build.bldpkg_path(m), args)


def args_func(args, p):
    try:
        args.func(args, p)
    except RuntimeError as e:
        sys.exit("Error: %s" % e)
    except Exception as e:
        if e.__class__.__name__ not in ('ScannerError', 'ParserError'):
            message = """\
An unexpected error has occurred, please consider sending the
following traceback to the conda GitHub issue tracker at:

    https://github.com/conda/conda-build/issues

Include the output of the command 'conda info' in your report.

"""
            print(message, file=sys.stderr)
        raise  # as if we did not catch it

if __name__ == '__main__':
    main()
