# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import argparse
import logging
import sys
import warnings
from itertools import chain
from os.path import abspath, expanduser, expandvars
from pathlib import Path

import filelock
from conda.auxlib.ish import dals
from conda.common.io import dashlist
from glob2 import glob

import conda_build.api as api
import conda_build.build as build
import conda_build.source as source
import conda_build.utils as utils
from conda_build.cli.actions import KeyValueAction
from conda_build.cli.main_render import get_render_parser
from conda_build.conda_interface import (
    add_parser_channels,
    binstar_upload,
    cc_conda_build,
)
from conda_build.config import Config, get_channel_urls, zstd_compression_level_default
from conda_build.utils import LoggingContext


def parse_args(args):
    p = get_render_parser()
    p.description = dals(
        """
        Tool for building conda packages. A conda package is a binary tarball
        containing system-level libraries, Python modules, executable programs, or
        other components. conda keeps track of dependencies between packages and
        platform specifics, making it simple to create working environments from
        different sets of packages.
        """
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Only check (validate) the recipe.",
    )
    p.add_argument(
        "--no-anaconda-upload",
        action="store_false",
        help="Do not ask to upload the package to anaconda.org.",
        dest="anaconda_upload",
        default=binstar_upload,
    )
    p.add_argument(
        "--no-binstar-upload",
        action="store_false",
        help=argparse.SUPPRESS,
        dest="anaconda_upload",
        default=binstar_upload,
    )
    p.add_argument(
        "--no-include-recipe",
        action="store_false",
        help="Don't include the recipe inside the built package.",
        dest="include_recipe",
        default=cc_conda_build.get("include_recipe", "true").lower() == "true",
    )
    p.add_argument(
        "-s",
        "--source",
        action="store_true",
        help="Only obtain the source (but don't build).",
    )
    p.add_argument(
        "-t",
        "--test",
        action="store_true",
        help="Test package (assumes package is already built).  RECIPE_DIR argument must be a "
        "path to built package .tar.bz2 file.",
    )
    p.add_argument(
        "--no-test",
        action="store_true",
        dest="notest",
        help="Do not test the package.",
    )
    p.add_argument(
        "-b",
        "--build-only",
        action="store_true",
        help="""Only run the build, without any post processing or
        testing. Implies --no-test and --no-anaconda-upload.""",
    )
    p.add_argument(
        "-p",
        "--post",
        action="store_true",
        help="Run the post-build logic. Implies --no-anaconda-upload.",
    )
    p.add_argument(
        "-p",
        "--test-run-post",
        action="store_true",
        help="Run the post-build logic during testing.",
    )
    p.add_argument(
        "recipe",
        metavar="RECIPE_PATH",
        nargs="+",
        help="Path to recipe directory.  Pass 'purge' here to clean the "
        "work and test intermediates. Pass 'purge-all' to also remove "
        "previously built packages.",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help=(
            "Skip recipes for which there already exists an existing build "
            "(locally or in the channels)."
        ),
        default=cc_conda_build.get("skip_existing", "false").lower() == "true",
    )
    p.add_argument(
        "--keep-old-work",
        action="store_true",
        dest="keep_old_work",
        help="Do not remove anything from environment, even after successful "
        "build and test.",
    )
    p.add_argument(
        "--dirty",
        action="store_true",
        help="Do not remove work directory or _build environment, "
        "to speed up debugging.  Does not apply patches or download source.",
    )
    p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="do not display progress bar",
        default=cc_conda_build.get("quiet", "false").lower() == "true",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Show debug output from source checkouts and conda",
    )
    p.add_argument(
        "--token",
        help="Token to pass through to anaconda upload",
        default=cc_conda_build.get("anaconda_token"),
    )
    p.add_argument(
        "--user",
        help="User/organization to upload packages to on anaconda.org or pypi",
        default=cc_conda_build.get("user"),
    )
    p.add_argument(
        "--label",
        action="append",
        dest="labels",
        default=[],
        help="Label argument to pass through to anaconda upload",
    )
    p.add_argument(
        "--no-force-upload",
        help="Disable force upload to anaconda.org, preventing overwriting any existing packages",
        dest="force_upload",
        default=True,
        action="store_false",
    )
    p.add_argument(
        "--zstd-compression-level",
        help=(
            "When building v2 packages, set the compression level used by "
            "conda-package-handling. "
            f"Defaults to {zstd_compression_level_default}."
        ),
        type=int,
        choices=range(1, 23),
        default=cc_conda_build.get(
            "zstd_compression_level", zstd_compression_level_default
        ),
    )
    pypi_grp = p.add_argument_group("PyPI upload parameters (twine)")
    pypi_grp.add_argument(
        "--password",
        help="password to use when uploading packages to pypi",
    )
    pypi_grp.add_argument(
        "--sign", default=False, help="sign files when uploading to pypi"
    )
    pypi_grp.add_argument(
        "--sign-with",
        default="gpg",
        dest="sign_with",
        help="program to use to sign files when uploading to pypi",
    )
    pypi_grp.add_argument(
        "--identity", help="GPG identity to use to sign files when uploading to pypi"
    )
    pypi_grp.add_argument(
        "--config-file",
        help="path to .pypirc file to use when uploading to pypi",
        default=(
            abspath(expanduser(expandvars(cc_conda_build.get("pypirc"))))
            if cc_conda_build.get("pypirc")
            else cc_conda_build.get("pypirc")
        ),
    )
    pypi_grp.add_argument(
        "--repository",
        "-r",
        help="PyPI repository to upload to",
        default=cc_conda_build.get("pypi_repository", "pypitest"),
    )
    p.add_argument(
        "--no-activate",
        action="store_false",
        help="do not activate the build and test envs; just prepend to PATH",
        dest="activate",
        default=cc_conda_build.get("activate", "true").lower() == "true",
    )
    p.add_argument(
        "--no-build-id",
        action="store_false",
        help=(
            "do not generate unique build folder names.  Use if having issues with "
            "paths being too long.  Deprecated, please use --build-id-pat='' instead"
        ),
        dest="set_build_id",
        # note: inverted - dest stores positive logic
        default=cc_conda_build.get("set_build_id", "true").lower() == "true",
    )
    p.add_argument(
        "--build-id-pat",
        help=(
            "specify a templated pattern to use as build folder names.  Use if having issues with "
            "paths being too long."
        ),
        dest="build_id_pat",
        default=cc_conda_build.get("build_id_pat", "{n}_{t}"),
    )
    p.add_argument(
        "--croot",
        help=(
            "Build root folder.  Equivalent to CONDA_BLD_PATH, but applies only "
            "to this call of conda-build."
        ),
    )
    p.add_argument(
        "--verify",
        action="store_true",
        help="run verification on recipes or packages when building",
        default=cc_conda_build.get("verify", "true").lower() == "true",
    )
    p.add_argument(
        "--no-verify",
        action="store_false",
        dest="verify",
        help="do not run verification on recipes or packages when building",
        default=cc_conda_build.get("verify", "true").lower() == "true",
    )
    p.add_argument(
        "--strict-verify",
        action="store_true",
        dest="exit_on_verify_error",
        help="Exit if any conda-verify check fail, instead of only printing them",
        default=cc_conda_build.get("exit_on_verify_error", "false").lower() == "true",
    )
    p.add_argument(
        "--output-folder",
        help=(
            "folder to dump output package to.  Package are moved here if build or test succeeds."
            "  Destination folder must exist prior to using this."
        ),
        default=cc_conda_build.get("output_folder"),
    )
    p.add_argument(
        "--no-prefix-length-fallback",
        dest="prefix_length_fallback",
        action="store_false",
        help=(
            "Disable fallback to older 80 character prefix length if environment creation"
            " fails due to insufficient prefix length in dependency packages"
        ),
        default=True,
    )
    p.add_argument(
        "--prefix-length-fallback",
        dest="prefix_length_fallback",
        action="store_true",
        help=(
            "Disable fallback to older 80 character prefix length if environment creation"
            " fails due to insufficient prefix length in dependency packages"
        ),
        # this default will change to false in the future, when we deem that the community has
        #     had enough time to build long-prefix length packages.
        default=True,
    )
    p.add_argument(
        "--prefix-length",
        dest="_prefix_length",
        help=(
            "length of build prefix.  For packages with binaries that embed the path, this is"
            " critical to ensuring that your package can run as many places as possible.  Note"
            "that this value can be altered by the OS below conda-build (e.g. encrypted "
            "filesystems on Linux), and you should prefer to set --croot to a non-encrypted "
            "location instead, so that you maintain a known prefix length."
        ),
        # this default will change to false in the future, when we deem that the community has
        #     had enough time to build long-prefix length packages.
        default=255,
        type=int,
    )
    p.add_argument(
        "--no-locking",
        dest="locking",
        default=True,
        action="store_false",
        help=(
            "Disable locking, to avoid unresolved race condition issues.  Unsafe to run multiple "
            "builds at once on one system with this set."
        ),
    )
    p.add_argument(
        "--no-remove-work-dir",
        dest="remove_work_dir",
        default=True,
        action="store_false",
        help=(
            "Disable removal of the work dir before testing.  Be careful using this option, as"
            " you package may depend on files that are not included in the package, and may pass "
            "tests, but ultimately fail on installed systems."
        ),
    )
    p.add_argument(
        "--error-overlinking",
        dest="error_overlinking",
        action="store_true",
        help=(
            "Enable error when shared libraries from transitive dependencies are directly "
            "linked to any executables or shared libraries in built packages.  This is disabled "
            "by default, but will be enabled by default in conda-build 4.0."
        ),
        default=cc_conda_build.get("error_overlinking", "false").lower() == "true",
    )
    p.add_argument(
        "--no-error-overlinking",
        dest="error_overlinking",
        action="store_false",
        help=(
            "Disable error when shared libraries from transitive dependencies are directly "
            "linked to any executables or shared libraries in built packages.  This is currently "
            "the default behavior, but will change in conda-build 4.0."
        ),
        default=cc_conda_build.get("error_overlinking", "false").lower() == "true",
    )
    p.add_argument(
        "--error-overdepending",
        dest="error_overdepending",
        action="store_true",
        help=(
            "Enable error when packages with names beginning `lib` or which have "
            "`run_exports` are not auto-loaded by the OSes DSO loading mechanism by "
            "any of the files in this package."
        ),
        default=cc_conda_build.get("error_overdepending", "false").lower() == "true",
    )
    p.add_argument(
        "--no-error-overdepending",
        dest="error_overdepending",
        action="store_false",
        help=(
            "Disable error when packages with names beginning `lib` or which have "
            "`run_exports` are not auto-loaded by the OSes DSO loading mechanism by "
            "any of the files in this package."
        ),
        default=cc_conda_build.get("error_overdepending", "false").lower() == "true",
    )
    p.add_argument(
        "--long-test-prefix",
        action="store_true",
        help=(
            "Use a long prefix for the test prefix, as well as the build prefix.  Affects only "
            "Linux and Mac.  Prefix length matches the --prefix-length flag.  This is on by "
            "default in conda-build 3.0+"
        ),
        default=cc_conda_build.get("long_test_prefix", "true").lower() == "true",
    )
    p.add_argument(
        "--no-long-test-prefix",
        dest="long_test_prefix",
        action="store_false",
        help=(
            "Do not use a long prefix for the test prefix, as well as the build prefix."
            "  Affects only Linux and Mac.  Prefix length matches the --prefix-length flag.  "
        ),
        default=cc_conda_build.get("long_test_prefix", "true").lower() == "true",
    )
    p.add_argument(
        "--keep-going",
        "-k",
        action="store_true",
        help=(
            "When running tests, keep going after each failure.  Default is to stop on the first "
            "failure."
        ),
    )
    p.add_argument(
        "--cache-dir",
        help=(
            "Path to store the source files (archives, git clones, etc.) during the build."
        ),
        default=(
            abspath(expanduser(expandvars(cc_conda_build.get("cache_dir"))))
            if cc_conda_build.get("cache_dir")
            else cc_conda_build.get("cache_dir")
        ),
    )
    p.add_argument(
        "--no-copy-test-source-files",
        dest="copy_test_source_files",
        action="store_false",
        default=cc_conda_build.get("copy_test_source_files", "true").lower() == "true",
        help=(
            "Disables copying the files necessary for testing the package into "
            "the info/test folder.  Passing this argument means it may not be possible "
            "to test the package without internet access.  There is also a danger that "
            "the source archive(s) containing the files could become unavailable sometime "
            "in the future."
        ),
    )
    p.add_argument(
        "--merge-build-host",
        action="store_true",
        help=(
            "Merge the build and host directories, even when host section or compiler "
            "jinja2 is present"
        ),
        default=cc_conda_build.get("merge_build_host", "false").lower() == "true",
    )
    p.add_argument(
        "--stats-file",
        help=("File path to save build statistics to.  Stats are " "in JSON format"),
    )
    p.add_argument(
        "--extra-deps",
        nargs="+",
        help=(
            "Extra dependencies to add to all environment creation steps.  This "
            "is only enabled for testing with the -t or --test flag.  Change "
            "meta.yaml or use templates otherwise."
        ),
    )
    p.add_argument(
        "--extra-meta",
        nargs="*",
        action=KeyValueAction,
        help="Key value pairs of metadata to add to about.json. Should be "
        "defined as Key=Value with a space separating each pair.",
        metavar="KEY=VALUE",
    )
    p.add_argument(
        "--suppress-variables",
        action="store_true",
        help=(
            "Do not display value of environment variables specified in build.script_env."
        ),
    )

    add_parser_channels(p)
    args = p.parse_args(args)

    check_recipe(args.recipe)

    return p, args


def check_recipe(path_list):
    """Verify if the list of recipes received contain a path to a directory,
    if a path to a recipe is found it will give an warning.

    :param path_list: list of paths to recipes
    """
    for recipe in map(Path, path_list):
        if recipe.is_file() and recipe.name in utils.VALID_METAS:
            warnings.warn(
                (
                    f"RECIPE_PATH received is a file ({recipe}).\n"
                    "It should be a path to a folder.\n"
                    "Forcing conda-build to use the recipe file."
                ),
                UserWarning,
            )


def output_action(recipe, config):
    with LoggingContext(logging.CRITICAL + 1):
        config.verbose = False
        config.debug = False
        paths = api.get_output_file_paths(recipe, config=config)
        print("\n".join(sorted(paths)))


def source_action(recipe, config):
    metadata = api.render(recipe, config=config)[0][0]
    source.provide(metadata)
    print("Source tree in:", metadata.config.work_dir)


def test_action(recipe, config):
    return api.test(recipe, move_broken=False, config=config)


def check_action(recipe, config):
    return api.check(recipe, config=config)


def execute(args):
    _parser, args = parse_args(args)
    config = Config(**args.__dict__)
    build.check_external()

    # change globals in build module, see comment there as well
    config.channel_urls = get_channel_urls(args.__dict__)

    config.override_channels = args.override_channels
    config.verbose = not args.quiet or args.debug

    if "purge" in args.recipe:
        build.clean_build(config)
        return

    if "purge-all" in args.recipe:
        build.clean_build(config)
        config.clean_pkgs()
        return

    outputs = None
    if args.output:
        config.verbose = False
        config.quiet = True
        config.debug = False
        outputs = [output_action(recipe, config) for recipe in args.recipe]
    elif args.test:
        outputs = []
        failed_recipes = []
        recipes = chain.from_iterable(
            glob(abspath(recipe)) if "*" in recipe else [recipe]
            for recipe in args.recipe
        )
        for recipe in recipes:
            try:
                test_action(recipe, config)
            except:
                if not args.keep_going:
                    raise
                else:
                    failed_recipes.append(recipe)
                    continue
        if failed_recipes:
            print("Failed recipes:")
            dashlist(failed_recipes)
            sys.exit(len(failed_recipes))
        else:
            print("All tests passed")
    elif args.source:
        outputs = [source_action(recipe, config) for recipe in args.recipe]
    elif args.check:
        outputs = [check_action(recipe, config) for recipe in args.recipe]
    else:
        outputs = api.build(
            args.recipe,
            post=args.post,
            test_run_post=args.test_run_post,
            build_only=args.build_only,
            notest=args.notest,
            already_built=None,
            config=config,
            verify=args.verify,
            variants=args.variants,
            cache_dir=args.cache_dir,
        )

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
        print(
            "File lock on {} could not be obtained.  You might need to try fewer builds at once."
            "  Otherwise, run conda clean --lock".format(e.lock_file)
        )
        sys.exit(1)
    return
