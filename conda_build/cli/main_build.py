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

import filelock

import conda_build.api as api
import conda_build.build as build
import conda_build.utils as utils
from conda_build.cli.main_render import RecipeCompleter, get_render_parser
from conda_build.conda_interface import add_parser_channels, url_path, binstar_upload
import conda_build.source as source
from conda_build.utils import LoggingContext
from conda_build.config import Config

on_win = (sys.platform == 'win32')

logging.basicConfig(level=logging.INFO)


def parse_args(args):
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
        dest='anaconda_upload',
        default=binstar_upload,
    )
    p.add_argument(
        "--no-binstar-upload",
        action="store_false",
        help=argparse.SUPPRESS,
        dest='anaconda_upload',
        default=binstar_upload,
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
        metavar='RECIPE_PATH',
        nargs='+',
        choices=RecipeCompleter(),
        help="Path to recipe directory.  Pass 'purge' here to clean the "
        "work and test intermediates.",
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
        dest='dirty',
        help="Deprecated.  Same as --dirty."
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
        '--debug',
        action="store_true",
        help="Show debug output from source checkouts and conda",
    )
    p.add_argument(
        '--token',
        help="Token to pass through to anaconda upload"
    )
    p.add_argument(
        '--user',
        help="User/organization to upload packages to on anaconda.org or pypi"
    )
    pypi_grp = p.add_argument_group("PyPI upload parameters (twine)")
    pypi_grp.add_argument(
        '--password',
        help="password to use when uploading packages to pypi"
    )
    pypi_grp.add_argument(
        '--sign', default=False,
        help="sign files when uploading to pypi"
    )
    pypi_grp.add_argument(
        '--sign-with', default='gpg', dest='sign_with',
        help="program to use to sign files when uploading to pypi"
    )
    pypi_grp.add_argument(
        '--identity',
        help="GPG identity to use to sign files when uploading to pypi"
    )
    pypi_grp.add_argument(
        '--config-file',
        help="path to .pypirc file to use when uploading to pypi"
    )
    pypi_grp.add_argument(
        '--repository', '-r', default='pypitest',
        help="PyPI repository to upload to"
    )
    p.add_argument(
        "--no-activate",
        action="store_false",
        help="do not activate the build and test envs; just prepend to PATH",
        dest='activate',
    )
    p.add_argument(
        "--no-build-id",
        action="store_false",
        help=("do not generate unique build folder names.  Use if having issues with "
              "paths being too long."),
        dest='set_build_id',
    )
    p.add_argument(
        "--croot",
        help=("Build root folder.  Equivalent to CONDA_BLD_PATH, but applies only "
              "to this call of conda-build.")
    )
    p.add_argument(
        "--no-verify",
        action="store_true",
        help=("do not run verification on recipes or packages when building")
    )
    p.add_argument(
        "--output-folder",
        help=("folder to dump output package to.  Package are moved here if build or test succeeds."
              "  Destination folder must exist prior to using this.")
    )
    p.add_argument(
        "--no-prefix-length-fallback", dest='prefix_length_fallback',
        action="store_false",
        help=("Disable fallback to older 80 character prefix length if environment creation"
              " fails due to insufficient prefix length in dependency packages"),
        default=True,
    )
    p.add_argument(
        "--prefix-length-fallback", dest='prefix_length_fallback',
        action="store_true",
        help=("Disable fallback to older 80 character prefix length if environment creation"
              " fails due to insufficient prefix length in dependency packages"),
        # this default will change to false in the future, when we deem that the community has
        #     had enough time to build long-prefix length packages.
        default=True,
    )
    p.add_argument(
        "--prefix-length", dest='_prefix_length',
        help=("length of build prefix.  For packages with binaries that embed the path, this is"
              " critical to ensuring that your package can run as many places as possible.  Note"
              "that this value can be altered by the OS below conda-build (e.g. encrypted "
              "filesystems on Linux), and you should prefer to set --croot to a non-encrypted "
              "location instead, so that you maintain a known prefix length."),
        # this default will change to false in the future, when we deem that the community has
        #     had enough time to build long-prefix length packages.
        default=255, type=int,
    )
    p.add_argument(
        "--no-locking", dest='locking', default=True, action="store_false",
        help=("Disable locking, to avoid unresolved race condition issues.  Unsafe to run multiple"
              "builds at once on one system with this set.")
    )
    p.add_argument(
        "--no-remove-work-dir", dest='remove_work_dir', default=True, action="store_false",
        help=("Disable removal of the work dir before testing.  Be careful using this option, as"
              " you package may depend on files that are not included in the package, and may pass"
              "tests, but ultimately fail on installed systems.")
    )
    p.add_argument(
        "--long-test-prefix", default=True, action="store_false",
        help=("Use a long prefix for the test prefix, as well as the build prefix.  Affects only "
              "Linux and Mac.  Prefix length matches the --prefix-length flag.  This is on by "
              "default in conda-build 3.0+")
    )
    p.add_argument(
        "--no-long-test-prefix", dest="long_test_prefix", action="store_false",
        help=("Do not use a long prefix for the test prefix, as well as the build prefix."
              "  Affects only Linux and Mac.  Prefix length matches the --prefix-length flag.  ")
    )
    add_parser_channels(p)

    args = p.parse_args(args)
    return p, args


def output_action(recipe, config):
    with LoggingContext(logging.CRITICAL + 1):
        paths = api.get_output_file_paths(recipe)
        print('\n'.join(sorted(paths)))


def source_action(recipe, config):
    metadata = api.render(recipe, config=config)[0][0]
    source.provide(metadata)
    print('Source tree in:', metadata.config.work_dir)


def test_action(recipe, config):
    return api.test(recipe, move_broken=False, config=config)


def check_action(recipe, config):
    return api.check(recipe, config=config)


def execute(args):
    parser, args = parse_args(args)
    config = Config(**args.__dict__)
    build.check_external()

    # change globals in build module, see comment there as well
    channel_urls = args.__dict__.get('channel') or args.__dict__.get('channels') or ()
    config.channel_urls = []

    for url in channel_urls:
        # allow people to specify relative or absolute paths to local channels
        #    These channels still must follow conda rules - they must have the
        #    appropriate platform-specific subdir (e.g. win-64)
        if os.path.isdir(url):
            if not os.path.isabs(url):
                url = os.path.normpath(os.path.abspath(os.path.join(os.getcwd(), url)))
            url = url_path(url)
        config.channel_urls.append(url)

    config.override_channels = args.override_channels
    config.verbose = not args.quiet or args.debug

    if 'purge' in args.recipe:
        build.clean_build(config)
        return

    if 'purge-all' in args.recipe:
        build.clean_build(config)
        config.clean_pkgs()
        return

    action = None
    if args.output:
        action = output_action
        config.verbose = False
        config.quiet = True
        config.debug = False
    elif args.test:
        action = test_action
    elif args.source:
        action = source_action
    elif args.check:
        action = check_action

    if action:
        outputs = [action(recipe, config) for recipe in args.recipe]
    else:
        outputs = api.build(args.recipe, post=args.post, build_only=args.build_only,
                            notest=args.notest, already_built=None, config=config,
                            noverify=args.no_verify)

    if not args.output and len(utils.get_build_folders(config.croot)) > 0:
        build.print_build_intermediate_warning(config)
    return outputs


def main():
    try:
        execute(sys.argv[1:])
    except RuntimeError as e:
        print(str(e))
        sys.exit(1)
    except filelock.Timeout as e:
        print("File lock on {0} could not be obtained.  You might need to try fewer builds at once."
              "  Otherwise, run conda clean --lock".format(e.lock_file))
        sys.exit(1)
    return
