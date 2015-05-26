# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import argparse
import sys
from collections import deque
from glob import glob
from locale import getpreferredencoding
from os.path import exists

import conda.config as config
from conda.compat import PY3
from conda.cli.common import add_parser_channels

from conda_build import __version__, exceptions


def main():
    p = argparse.ArgumentParser(
        description='tool for building conda packages'
    )

    p.add_argument(
        "--check",
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
        help="Set the Python version used by conda build",
        metavar="PYTHON_VER",
    )
    p.add_argument(
        '--perl',
        action="append",
        help="Set the Perl version used by conda build",
        metavar="PERL_VER",
    )
    p.add_argument(
        '--numpy',
        action="append",
        help="Set the NumPy version used by conda build",
        metavar="NUMPY_VER",
    )
    p.add_argument(
        '--R',
        action="append",
        help="Set the R version used by conda build",
        metavar="R_VER",
    )
    add_parser_channels(p)
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
    print("Uploading to binstar")
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
    relocatable ELF libraries.  You can install patchelf using conda install
    patchelf.
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
    from conda_build.config import config
    from conda_build.metadata import MetaData

    check_external()

    all_versions = {
        'python': [26, 27, 33, 34],
        'numpy': [16, 17, 18, 19],
        'perl': None,
        'R': None,
        }
    conda_version = {
        'python': 'CONDA_PY',
        'numpy': 'CONDA_NPY',
        'perl': 'CONDA_PERL',
        'R': 'CONDA_R',
        }

    for lang in ['python', 'numpy', 'perl', 'R']:
        versions = getattr(args, lang)
        if not versions:
            continue
        if versions == ['all']:
            if all_versions[lang]:
                versions = all_versions[lang]
            else:
                parser.error("'all' is not supported for --%s" % lang)
        if len(versions) > 1:
            for ver in versions[:]:
                setattr(args, lang, [str(ver)])
                execute(args, parser)
                # This is necessary to make all combinations build.
                setattr(args, lang, versions)
            return
        else:
            version = int(versions[0].replace('.', ''))
            setattr(config, conda_version[lang], version)
        if not len(str(version)) == 2:
            if all_versions[lang]:
                raise RuntimeError("%s must be major.minor, like %s, not %s" %
                    (conda_version[lang], all_versions[lang][-1]/10, version))
            else:
                raise RuntimeError("%s must be major.minor, not %s" %
                    (conda_version[lang], version))


    with Locked(config.croot):
        recipes = deque(args.recipe)
        while recipes:
            arg = recipes.popleft()
            try_again = False
            # Don't use byte literals for paths in Python 2
            if not PY3:
                arg = arg.decode(getpreferredencoding() or 'utf-8')
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

            try:
                m = MetaData(recipe_dir)
            except exceptions.YamlParsingError as e:
                sys.stderr.write(e.error_msg())
                sys.exit(1)
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
                channel_urls = args.channel or ()
                try:
                    build.build(m, verbose=not args.quiet, post=post,
                        channel_urls=channel_urls, override_channels=args.override_channels)
                except RuntimeError as e:
                    error_str = str(e)
                    if error_str.startswith('No packages found') or error_str.startswith('Could not find some'):
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
                    build.test(m, verbose=not args.quiet,
                        channel_urls=channel_urls, override_channels=args.override_channels)
                binstar_upload = True

            if need_cleanup:
                shutil.rmtree(recipe_dir)

            if binstar_upload:
                handle_binstar_upload(build.bldpkg_path(m), args)


def args_func(args, p):
    try:
        args.func(args, p)
    except RuntimeError as e:
        if 'maximum recursion depth exceeded' in str(e):
            print_issue_message(e)
            raise
        sys.exit("Error: %s" % e)
    except Exception as e:
        print_issue_message(e)
        raise  # as if we did not catch it

def print_issue_message(e):
    if e.__class__.__name__ not in ('ScannerError', 'ParserError'):
        message = """\
An unexpected error has occurred, please consider sending the
following traceback to the conda GitHub issue tracker at:

    https://github.com/conda/conda-build/issues

Include the output of the command 'conda info' in your report.

"""
        print(message, file=sys.stderr)

if __name__ == '__main__':
    main()
