# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import argparse
import logging
import os
import sys
from collections import deque
from glob import glob
from locale import getpreferredencoding
import warnings

from .conda_interface import cc
from .conda_interface import add_parser_channels, PY3
from .conda_interface import delete_trash
from .conda_interface import NoPackagesFound, Unsatisfiable

from conda_build.build import bldpkg_path
from conda_build.index import update_index
from conda_build.main_render import get_render_parser
from conda_build.utils import find_recipe
from conda_build.main_render import (set_language_env_vars, RecipeCompleter, render_recipe)
on_win = (sys.platform == 'win32')

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__file__)


def main():
    p = get_render_parser()
    p.description = """
Tool for building conda packages. A conda package is a binary tarball
containing system-level libraries, Python modules, executable programs, or
other components. conda keeps track of dependencies between packages and
platform specifics, making it simple to create working environments from
different sets of packages."""
    p.add_argument(
        "--check",
        action="store_true",
        help="Only check (validate) the recipe.",
    )
    p.add_argument(
        "--no-anaconda-upload",
        action="store_false",
        help="Do not ask to upload the package to anaconda.org.",
        dest='binstar_upload',
        default=cc.binstar_upload,
    )
    p.add_argument(
        "--no-binstar-upload",
        action="store_false",
        help=argparse.SUPPRESS,
        dest='binstar_upload',
        default=cc.binstar_upload,
    )
    p.add_argument(
        "--no-include-recipe",
        action="store_false",
        help="Don't include the recipe inside the built package.",
        dest='include_recipe',
        default=True,
    )
    p.add_argument(
        '-s', "--source",
        action="store_true",
        help="Only obtain the source (but don't build).",
    )
    p.add_argument(
        '-t', "--test",
        action="store_true",
        help="Test package (assumes package is already built).  RECIPE_DIR argument can be either "
        "recipe directory, in which case source download may be necessary to resolve package"
        "version, or path to built package .tar.bz2 file, in which case no source is necessary.",
    )
    p.add_argument(
        '--no-test',
        action='store_true',
        dest='notest',
        help="Do not test the package.",
    )
    p.add_argument(
        '-b', '--build-only',
        action="store_true",
        help="""Only run the build, without any post processing or
        testing. Implies --no-test and --no-anaconda-upload.""",
    )
    p.add_argument(
        '-p', '--post',
        action="store_true",
        help="Run the post-build logic. Implies --no-test and --no-anaconda-upload.",
    )
    p.add_argument(
        'recipe',
        action="store",
        metavar='RECIPE_PATH',
        nargs='+',
        choices=RecipeCompleter(),
        help="Path to recipe directory.",
    )
    p.add_argument(
        '--skip-existing',
        action='store_true',
        help="""Skip recipes for which there already exists an existing build
        (locally or in the channels). """
    )
    p.add_argument(
        '--keep-old-work',
        action='store_true',
        help="""Keep any existing, old work directory. Useful if debugging across
        callstacks involving multiple packages/recipes. """
    )
    p.add_argument(
        '--dirty',
        action='store_true',
        help='Do not remove work directory or _build environment, '
        'to speed up debugging.  Does not apply patches or download source.'
    )
    p.add_argument(
        '-q', "--quiet",
        action="store_true",
        help="do not display progress bar",
    )
    p.add_argument(
        '--token',
        help="Token to pass through to anaconda upload"
    )
    p.add_argument(
        '--user',
        help="User/organization to upload packages to on anaconda.org"
    )
    p.add_argument(
        "--no-activate",
        action="store_false",
        help="do not display progress bar",
        dest='activate',
    )
    p.add_argument(
        '--debug',
        action='store_true',
        help="show debugging output from conda and conda-build",
    )
    add_parser_channels(p)
    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)


def handle_binstar_upload(path, args):
    import subprocess
    from conda_build.external import find_executable

    upload = False
    if args.token or args.user:
        args.yes = True
        upload = True
    # this is the default, for no explicit argument.
    # remember that args.binstar_upload takes defaults from condarc
    elif args.binstar_upload is None:
        args.yes = False
        args.dry_run = False
    # rc file has uploading explicitly turned off
    elif args.binstar_upload is False:
        print("# Automatic uploading is disabled")
    else:
        upload = True

    no_upload_message = """\
# If you want to upload this package to anaconda.org later, type:
#
# $ anaconda upload %s
#
# To have conda build upload to anaconda.org automatically, use
# $ conda config --set anaconda_upload yes
""" % path
    if not upload:
        print(no_upload_message)
        return

    binstar = find_executable('anaconda')
    if binstar is None:
        print(no_upload_message)
        sys.exit('''
Error: cannot locate anaconda command (required for upload)
# Try:
# $ conda install anaconda-client
''')
    print("Uploading to anaconda.org")
    cmd = [binstar, ]

    if hasattr(args, "token") and args.token:
        cmd.extend(['--token', args.token])
    cmd.append('upload')
    if hasattr(args, "user") and args.user:
        cmd.extend(['--user', args.user])
    cmd.append(path)
    try:
        subprocess.call(cmd)
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
    from os import makedirs
    from os.path import abspath, isdir, isfile

    from .conda_interface import cc

    import conda_build.build as build
    import conda_build.source as source
    from conda_build.config import config

    check_external()

    # change globals in build module, see comment there as well
    build.channel_urls = args.channel or ()
    build.override_channels = args.override_channels
    build.verbose = not args.quiet or args.debug

    if on_win:
        try:
            # needs to happen before any c extensions are imported that might be
            # hard-linked by files in the trash. one of those is markupsafe,
            # used by jinja2. see https://github.com/conda/conda-build/pull/520
            delete_trash(None)
        except:
            # when we can't delete the trash, don't crash on AssertionError,
            # instead inform the user and try again next time.
            # see https://github.com/conda/conda-build/pull/744
            warnings.warn("Cannot delete trash; some c extension has been "
                          "imported that is hard-linked by files in the trash. "
                          "Will try again on next run.")

    set_language_env_vars(args, parser, execute=execute)

    if args.skip_existing:
        for d in config.bldpkgs_dirs:
            if not isdir(d):
                makedirs(d)
            update_index(d)
        arg_channels = ['local']
        if args.channel:
            arg_channels.extend(args.channel)
        index = build.get_build_index(clear_cache=True,
                                      arg_channels=arg_channels)

    already_built = set()
    to_build_recursive = []
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

        # recurse looking for meta.yaml that is potentially not in immediate folder
        recipe_dir = find_recipe(recipe_dir)
        if not isdir(recipe_dir):
            sys.exit("Error: no such directory: %s" % recipe_dir)

        # this fully renders any jinja templating, throwing an error if any data is missing
        m, need_source_download, need_reparse_in_env = render_recipe(recipe_dir,
                                                                     no_download_source=False,
                                                                     verbose=False,
                                                                     dirty=args.dirty)

        if m.get_value('build/noarch_python'):
            config.noarch = True

        if args.check and len(args.recipe) > 1:
            print(m.path)
        m.check_fields()
        if args.check:
            continue
        if m.skip():
            print("Skipped: The %s recipe defines build/skip for this "
                    "configuration." % m.dist())
            continue
        if args.skip_existing:
            urls = cc.get_rc_urls() + cc.get_local_urls() + ['local', ]
            if args.channel:
                urls.extend(args.channel)

            # will be empty if none found, and evalute to False
            package_exists = [url for url in urls if url + '::' + m.pkg_fn() in index]
            if (package_exists or m.pkg_fn() in index or m.pkg_fn() in already_built):
                print(m.dist(), "is already built in {0}, skipping.".format(package_exists))
                continue
        if args.output:
            print(bldpkg_path(m))
            continue
        elif args.test:
            build.test(m, move_broken=False, debug=args.debug)
        elif args.source:
            if need_source_download:
                source.provide(m.path, m.get_section('source'), verbose=build.verbose)
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
                build.build(m, post=post,
                            include_recipe=args.include_recipe,
                            keep_old_work=args.keep_old_work,
                            need_source_download=need_source_download,
                            need_reparse_in_env=need_reparse_in_env,
                            dirty=args.dirty, activate=args.activate,
                            debug=args.debug)
            except (NoPackagesFound, Unsatisfiable) as e:
                error_str = str(e)
                # Typically if a conflict is with one of these
                # packages, the other package needs to be rebuilt
                # (e.g., a conflict with 'python 3.5*' and 'x' means
                # 'x' isn't build for Python 3.5 and needs to be
                # rebuilt).
                skip_names = ['python', 'r']
                add_recipes = []
                for line in error_str.splitlines():
                    if not line.startswith('  - '):
                        continue
                    pkg = line.lstrip('  - ').split(' -> ')[-1]
                    pkg = pkg.strip().split(' ')[0]
                    if pkg in skip_names:
                        sys.stderr.write("Warning: package conflict - you may have unresolved "
                                         "dependencies. Try to conda install each of your "
                                         "dependencies to figure out which has unresolved "
                                         "dependencies.")
                        continue
                    recipe_glob = glob(pkg + '-[v0-9][0-9.]*')
                    if os.path.exists(pkg):
                        recipe_glob.append(pkg)
                    if recipe_glob:
                        try_again = True
                        for recipe_dir in recipe_glob:
                            if pkg in to_build_recursive:
                                sys.exit(str(e))
                            print(error_str)
                            print(("Missing dependency {0}, but found" +
                                    " recipe directory, so building " +
                                    "{0} first").format(pkg))
                            add_recipes.append(recipe_dir)
                            to_build_recursive.append(pkg)
                    else:
                        raise
                recipes.appendleft(arg)
                recipes.extendleft(reversed(add_recipes))

            if try_again:
                continue

            if not args.notest:
                build.test(m, activate=args.activate, debug=args.debug)

        if need_cleanup:
            shutil.rmtree(recipe_dir)

        # outputs message, or does upload, depending on value of args.binstar_upload
        handle_binstar_upload(build.bldpkg_path(m), args)

        already_built.add(m.pkg_fn())


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
