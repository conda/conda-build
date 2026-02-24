# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import logging
import os
import pkgutil
import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from conda.base.context import context

from .. import api
from ..config import Config
from ..exceptions import CondaBuildUserError

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace
    from collections.abc import Sequence

thisdir = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(level=logging.INFO)

SUPPORTED_RECIPE_VERSIONS = ("v0", "v1")


def parse_args(args: Sequence[str] | None) -> tuple[ArgumentParser, Namespace]:
    from conda.cli.conda_argparse import ArgumentParser

    parser = ArgumentParser(
        prog="conda skeleton",
        description="""
Generates a boilerplate/skeleton recipe, which you can then edit to create a
full recipe. Some simple skeleton recipes may not even need edits.
        """,
        epilog="""
Run --help on the subcommands like 'conda skeleton pypi --help' to see the
options available.
        """,
    )

    # Flag for using rattler-build
    parser.add_argument(
        "--output-format",
        choices=SUPPORTED_RECIPE_VERSIONS,
        default="v0",
        help="Output format for recipe generation.",
    )

    repos = parser.add_subparsers(dest="repo")

    skeletons = [
        name
        for _, name, _ in pkgutil.iter_modules([os.path.join(thisdir, "../skeletons")])
    ]
    for skeleton in skeletons:
        if skeleton.startswith("_"):
            continue
        module = import_module("conda_build.skeletons." + skeleton)
        module.add_parser(repos)

    return parser, parser.parse_args(args)


def execute(args: Sequence[str] | None = None) -> int:
    parser, parsed = parse_args(args)
    context.__init__(argparse_args=parsed)

    config = Config(**parsed.__dict__)

    if not parsed.repo:
        parser.print_help()
        sys.exit()

    if parsed.output_format == "v1":
        try:
            from conda_recipe_manager.parser.recipe_parser_convert import (
                RecipeParserConvert,
            )
        except ImportError:
            raise CondaBuildUserError(
                "Please install conda-recipe-manager to enable v1 recipe generation."
            )

    api.skeletonize(
        parsed.packages,
        parsed.repo,
        output_dir=parsed.output_dir,
        recursive=parsed.recursive,
        version=parsed.version,
        config=config,
    )

    if parsed.output_format == "v1":
        for package in parsed.packages:
            v0_recipe_path = Path(os.path.join(parsed.output_dir, package, "meta.yaml"))
            v1_recipe_path = Path(
                os.path.join(parsed.output_dir, package, "recipe.yaml")
            )

            recipe_content = RecipeParserConvert.pre_process_recipe_text(
                v0_recipe_path.read_text()
            )
            recipe_converter = RecipeParserConvert(recipe_content)
            v1_content, _, _ = recipe_converter.render_to_v1_recipe_format()
            v1_recipe_path.write_text(v1_content, encoding="utf-8")
            os.remove(v0_recipe_path)

    return 0
