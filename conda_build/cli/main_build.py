# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import argparse
import logging
import sys
import warnings
from glob import glob
from itertools import chain
from os.path import abspath, expanduser, expandvars
from pathlib import Path
from typing import TYPE_CHECKING

from conda.auxlib.ish import dals
from conda.base.context import context
from conda.common.io import dashlist

from .. import api, build, source, utils
from ..config import (
    get_channel_urls,
    get_or_merge_config,
    zstd_compression_level_default,
)
from ..utils import LoggingContext
from .actions import KeyValueAction
from .main_render import get_render_parser

try:
    from conda.cli.helpers import add_parser_channels
except ImportError:
    # conda<23.11
    from conda.cli.conda_argparse import add_parser_channels

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace
    from typing import Sequence


def parse_args(args: Sequence[str] | None) -> tuple[ArgumentParser, Namespace]:
    parser = get_render_parser()
    parser.prog = "conda build"
    parser.description = dals(
        """
        Tool for building conda packages. A conda package is a binary tarball
        containing system-level libraries, Python modules, executable programs, or
        other components. conda keeps track of dependencies between packages and
        platform specifics, making it simple to create working environments from
        different sets of packages.
        """
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check (validate) the recipe.",
    )
    parser.add_argument(
        "--no-anaconda-upload",
        action="store_false",
        help="Do not ask to upload the package to anaconda.org.",
        dest="anaconda_upload",
        default=context.binstar_upload,
    )
    parser.add_argument(
        "--no-binstar-upload",
        action="store_false",
        help=argparse.SUPPRESS,
        dest="anaconda_upload",
        default=context.binstar_upload,
    )
    parser.add_argument(
        "--no-include-recipe",
        action="store_false",
        help="Don't include the recipe inside the built package.",
        dest="include_recipe",
        default=context.conda_build.get("include_recipe", "true").lower() == "true",
    )
    parser.add_argument(
        "-s",
        "--source",
        action="store_true",
        help="Only obtain the source (but don't build).",
    )
    parser.add_argument(
        "-t",
        "--test",
        action="store_true",
        help="Test package (assumes package is already built).  RECIPE_DIR argument must be a "
        "path to built package .tar.bz2 file.",
    )
    parser.add_argument(
        "--no-test",
        action="store_true",
        dest="notest",
        help="Do not test the package.",
    )
    parser.add_argument(
        "-b",
        "--build-only",
        action="store_true",
        help="""Only run the build, without any post processing or
        testing. Implies --no-test and --no-anaconda-upload.""",
    )
    parser.add_argument(
        "-p",
        "--post",
        action="store_true",
        help="Run the post-build logic. Implies --no-anaconda-upload.",
    )
    parser.add_argument(
        "-p",
        "--test-run-post",
        action="store_true",
        help="Run the post-build logic during testing.",
    )
    parser.add_argument(
        "recipe",
        metavar="RECIPE_PATH",
        nargs="+",
        help="Path to recipe directory.  Pass 'purge' here to clean the "
        "work and test intermediates. Pass 'purge-all' to also remove "
        "previously built packages.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help=(
            "Skip recipes for which there already exists an existing build "
            "(locally or in the channels)."
        ),
        default=context.conda_build.get("skip_existing", "false").lower() == "true",
    )
    parser.add_argument(
        "--keep-old-work",
        action="store_true",
        dest="keep_old_work",
        help="Do not remove anything from environment, even after successful "
        "build and test.",
    )
    parser.add_argument(
        "--dirty",
        action="store_true",
        help="Do not remove work directory or _build environment, "
        "to speed up debugging.  Does not apply patches or download source.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="do not display progress bar",
        default=context.conda_build.get("quiet", "false").lower() == "true",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show debug output from source checkouts and conda",
    )
    parser.add_argument(
        "--token",
        help="Token to pass through to anaconda upload",
        default=context.conda_build.get("anaconda_token"),
    )
    parser.add_argument(
        "--user",
        help="User/organization to upload packages to on anaconda.org or pypi",
        default=context.conda_build.get("user"),
    )
    parser.add_argument(
        "--label",
        action="append",
        dest="labels",
        default=[],
        help="Label argument to pass through to anaconda upload",
    )
    parser.add_argument(
        "--no-force-upload",
        help="Disable force upload to anaconda.org, preventing overwriting any existing packages",
        dest="force_upload",
        default=True,
        action="store_false",
    )
    parser.add_argument(
        "--zstd-compression-level",
        help=(
            "When building v2 packages, set the compression level used by "
            "conda-package-handling. "
            f"Defaults to {zstd_compression_level_default}."
        ),
        type=int,
        choices=range(1, 23),
        default=context.conda_build.get(
            "zstd_compression_level", zstd_compression_level_default
        ),
    )
    pypi_grp = parser.add_argument_group("PyPI upload parameters (twine)")
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
            abspath(expanduser(expandvars(pypirc)))
            if (pypirc := context.conda_build.get("pypirc"))
            else None
        ),
    )
    pypi_grp.add_argument(
        "--repository",
        "-r",
        help="PyPI repository to upload to",
        default=context.conda_build.get("pypi_repository", "pypitest"),
    )
    parser.add_argument(
        "--no-activate",
        action="store_false",
        help="do not activate the build and test envs; just prepend to PATH",
        dest="activate",
        default=context.conda_build.get("activate", "true").lower() == "true",
    )
    parser.add_argument(
        "--no-build-id",
        action="store_false",
        help=(
            "do not generate unique build folder names.  Use if having issues with "
            "paths being too long.  Deprecated, please use --build-id-pat='' instead"
        ),
        dest="set_build_id",
        # note: inverted - dest stores positive logic
        default=context.conda_build.get("set_build_id", "true").lower() == "true",
    )
    parser.add_argument(
        "--build-id-pat",
        help=(
            "specify a templated pattern to use as build folder names.  Use if having issues with "
            "paths being too long."
        ),
        dest="build_id_pat",
        default=context.conda_build.get("build_id_pat", "{n}_{t}"),
    )
    parser.add_argument(
        "--croot",
        help=(
            "Build root folder.  Equivalent to CONDA_BLD_PATH, but applies only "
            "to this call of conda-build."
        ),
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="run verification on recipes or packages when building",
        default=context.conda_build.get("verify", "true").lower() == "true",
    )
    parser.add_argument(
        "--no-verify",
        action="store_false",
        dest="verify",
        help="do not run verification on recipes or packages when building",
        default=context.conda_build.get("verify", "true").lower() == "true",
    )
    parser.add_argument(
        "--strict-verify",
        action="store_true",
        dest="exit_on_verify_error",
        help="Exit if any conda-verify check fail, instead of only printing them",
        default=context.conda_build.get("exit_on_verify_error", "false").lower()
        == "true",
    )
    parser.add_argument(
        "--output-folder",
        help=(
            "folder to dump output package to.  Package are moved here if build or test succeeds."
            "  Destination folder must exist prior to using this."
        ),
        default=context.conda_build.get("output_folder"),
    )
    parser.add_argument(
        "--no-prefix-length-fallback",
        dest="prefix_length_fallback",
        action="store_false",
        help=(
            "Disable fallback to older 80 character prefix length if environment creation"
            " fails due to insufficient prefix length in dependency packages"
        ),
        default=True,
    )
    parser.add_argument(
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
    parser.add_argument(
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
    parser.add_argument(
        "--no-locking",
        dest="locking",
        default=True,
        action="store_false",
        help=(
            "Disable locking, to avoid unresolved race condition issues.  Unsafe to run multiple "
            "builds at once on one system with this set."
        ),
    )
    parser.add_argument(
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
    parser.add_argument(
        "--error-overlinking",
        dest="error_overlinking",
        action="store_true",
        help=(
            "Enable error when shared libraries from transitive dependencies are directly "
            "linked to any executables or shared libraries in built packages.  This is disabled "
            "by default, but will be enabled by default in conda-build 4.0."
        ),
        default=context.conda_build.get("error_overlinking", "false").lower() == "true",
    )
    parser.add_argument(
        "--no-error-overlinking",
        dest="error_overlinking",
        action="store_false",
        help=(
            "Disable error when shared libraries from transitive dependencies are directly "
            "linked to any executables or shared libraries in built packages.  This is currently "
            "the default behavior, but will change in conda-build 4.0."
        ),
        default=context.conda_build.get("error_overlinking", "false").lower() == "true",
    )
    parser.add_argument(
        "--error-overdepending",
        dest="error_overdepending",
        action="store_true",
        help=(
            "Enable error when packages with names beginning `lib` or which have "
            "`run_exports` are not auto-loaded by the OSes DSO loading mechanism by "
            "any of the files in this package."
        ),
        default=context.conda_build.get("error_overdepending", "false").lower()
        == "true",
    )
    parser.add_argument(
        "--no-error-overdepending",
        dest="error_overdepending",
        action="store_false",
        help=(
            "Disable error when packages with names beginning `lib` or which have "
            "`run_exports` are not auto-loaded by the OSes DSO loading mechanism by "
            "any of the files in this package."
        ),
        default=context.conda_build.get("error_overdepending", "false").lower()
        == "true",
    )
    parser.add_argument(
        "--long-test-prefix",
        action="store_true",
        help=(
            "Use a long prefix for the test prefix, as well as the build prefix.  Affects only "
            "Linux and Mac.  Prefix length matches the --prefix-length flag.  This is on by "
            "default in conda-build 3.0+"
        ),
        default=context.conda_build.get("long_test_prefix", "true").lower() == "true",
    )
    parser.add_argument(
        "--no-long-test-prefix",
        dest="long_test_prefix",
        action="store_false",
        help=(
            "Do not use a long prefix for the test prefix, as well as the build prefix."
            "  Affects only Linux and Mac.  Prefix length matches the --prefix-length flag.  "
        ),
        default=context.conda_build.get("long_test_prefix", "true").lower() == "true",
    )
    parser.add_argument(
        "--keep-going",
        "-k",
        action="store_true",
        help=(
            "When running tests, keep going after each failure.  Default is to stop on the first "
            "failure."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        help=(
            "Path to store the source files (archives, git clones, etc.) during the build."
        ),
        default=(
            abspath(expanduser(expandvars(cache_dir)))
            if (cache_dir := context.conda_build.get("cache_dir"))
            else None
        ),
    )
    parser.add_argument(
        "--no-copy-test-source-files",
        dest="copy_test_source_files",
        action="store_false",
        default=context.conda_build.get("copy_test_source_files", "true").lower()
        == "true",
        help=(
            "Disables copying the files necessary for testing the package into "
            "the info/test folder.  Passing this argument means it may not be possible "
            "to test the package without internet access.  There is also a danger that "
            "the source archive(s) containing the files could become unavailable sometime "
            "in the future."
        ),
    )
    parser.add_argument(
        "--merge-build-host",
        action="store_true",
        help=(
            "Merge the build and host directories, even when host section or compiler "
            "jinja2 is present"
        ),
        default=context.conda_build.get("merge_build_host", "false").lower() == "true",
    )
    parser.add_argument(
        "--stats-file",
        help="File path to save build statistics to.  Stats are in JSON format",
    )
    parser.add_argument(
        "--extra-deps",
        nargs="+",
        help=(
            "Extra dependencies to add to all environment creation steps.  This "
            "is only enabled for testing with the -t or --test flag.  Change "
            "meta.yaml or use templates otherwise."
        ),
    )
    parser.add_argument(
        "--extra-meta",
        nargs="*",
        action=KeyValueAction,
        help="Key value pairs of metadata to add to about.json. Should be "
        "defined as Key=Value with a space separating each pair.",
        metavar="KEY=VALUE",
    )
    parser.add_argument(
        "--suppress-variables",
        action="store_true",
        help=(
            "Do not display value of environment variables specified in build.script_env."
        ),
    )

    add_parser_channels(parser)

    parsed = parser.parse_args(args)
    check_recipe(parsed.recipe)
    return parser, parsed


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


def execute(args: Sequence[str] | None = None) -> int:
    _, parsed = parse_args(args)
    context.__init__(argparse_args=parsed)

    config = get_or_merge_config(None, **parsed.__dict__)

    # change globals in build module, see comment there as well
    config.channel_urls = get_channel_urls(parsed.__dict__)

    config.verbose = not parsed.quiet or parsed.debug

    if "purge" in parsed.recipe:
        build.clean_build(config)
        return 0

    if "purge-all" in parsed.recipe:
        build.clean_build(config)
        config.clean_pkgs()
        return 0

    if parsed.output:
        config.verbose = False
        config.quiet = True
        config.debug = False
        for recipe in parsed.recipe:
            output_action(recipe, config)
        return 0

    if parsed.test:
        failed_recipes = []
        recipes = chain.from_iterable(
            glob(abspath(recipe), recursive=True) if "*" in recipe else [recipe]
            for recipe in parsed.recipe
        )
        for recipe in recipes:
            try:
                test_action(recipe, config)
            except:
                if not parsed.keep_going:
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
    elif parsed.source:
        for recipe in parsed.recipe:
            source_action(recipe, config)
    elif parsed.check:
        for recipe in parsed.recipe:
            check_action(recipe, config)
    else:
        api.build(
            parsed.recipe,
            post=parsed.post,
            test_run_post=parsed.test_run_post,
            build_only=parsed.build_only,
            notest=parsed.notest,
            already_built=None,
            config=config,
            verify=parsed.verify,
            variants=parsed.variants,
            cache_dir=parsed.cache_dir,
        )

    if utils.get_build_folders(config.croot):
        build.print_build_intermediate_warning(config)

    return 0
