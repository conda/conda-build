# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import logging
import os
import pkgutil
import subprocess
import sys
from importlib import import_module
from typing import TYPE_CHECKING

from conda.base.context import context

from .. import api
from ..config import Config

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace
    from collections.abc import Sequence

thisdir = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(level=logging.INFO)


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
        "--use-rattler",
        action="store_true",
        help="Generate recipes using rattler-build",
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

    if parsed.use_rattler:
        if parsed.repo == "rpm":
            print(
                f"Warning: rattler-build does not support '{parsed.repo}' skeleton"
                "Falling back to conda-skeleton recipe generation.",
                file=sys.stderr,
            )
        else:
            cmd = [
                "rattler-build",
                "generate-recipe",
                parsed.repo,
                *parsed.packages,
                "-w",
            ]
            try:
                subprocess.run(cmd, text=True, check=True)
                return 0
            except subprocess.CalledProcessError as e:
                print(f"rattler-build failed: {e}", file=sys.stderr)
                return e.returncode

    api.skeletonize(
        parsed.packages,
        parsed.repo,
        output_dir=parsed.output_dir,
        recursive=parsed.recursive,
        version=parsed.version,
        config=config,
    )

    return 0
