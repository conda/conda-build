# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace

logging.basicConfig(level=logging.INFO)

_DEPRECATION_MSG = (
    "'conda develop' is deprecated and will be removed in a future release of conda-build.\n"
    "Please use pip editable installs instead, for example:\n"
    "  python -m pip install -e PATH\n"
    "To uninstall, use:\n"
    "  python -m pip uninstall <package>\n"
    "If you previously relied on conda.pth, you may remove entries manually from that file."
)


def parse_args(args: Sequence[str] | None) -> tuple[ArgumentParser, Namespace]:
    from argparse import ArgumentParser

    parser = ArgumentParser(
        prog="conda develop",
        description=(
            "Install a Python package in 'development mode'.\n\n"
            "Deprecated: 'conda develop' is deprecated and will be removed in a future release.\n"
            "Use pip editable installs instead, e.g.:\n"
            "  python -m pip install -e PATH\n\n"
            "This works by creating a conda.pth file in site-packages."
        ),
    )

    parser.add_argument(
        "source",
        metavar="PATH",
        nargs="*",
        help="Path to the source directory.",
    )
    parser.add_argument(
        "-npf",
        "--no-pth-file",
        action="store_true",
        help=(
            "Relink compiled extension dependencies against libraries found in current environment. "
            "Do not add source to conda.pth. "
            "(Deprecated: prefer 'python -m pip install -e PATH'.)"
        ),
    )
    parser.add_argument(
        "-b",
        "--build_ext",
        action="store_true",
        help=(
            "Build extensions inplace, invoking: "
            "python setup.py build_ext --inplace; "
            "add to conda.pth; relink runtime libraries to environment's lib/. "
            "(Deprecated: prefer standard build workflows via pip/build backends.)"
        ),
    )
    parser.add_argument(
        "-c",
        "--clean",
        action="store_true",
        help=(
            "Invoke clean on setup.py: python setup.py clean. "
            "Use with --build_ext to clean before building. "
            "(Deprecated.)"
        ),
    )
    parser.add_argument(
        "-u",
        "--uninstall",
        action="store_true",
        help=(
            "Removes package if installed in 'development mode' by deleting path from conda.pth file. "
            "Ignore other options - just uninstall and exit. "
            "(Deprecated: use 'python -m pip uninstall <package>'.)"
        ),
    )

    return parser, parser.parse_args(args)


def main(argv: Sequence[str] | None = None) -> int:
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning)
    # Avoid parsing unrelated process arguments if argv is None
    if argv is None:
        argv = []
    _, ns = parse_args(argv)
    logging.getLogger(__name__).info(
        "No-op: 'conda develop' is deprecated. Parsed args: %s", vars(ns)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())