# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
from argparse import ArgumentError

from conda_build import utils
from conda_build.utils import CONDA_PACKAGE_EXTENSIONS

CONDA_PKG_OR_RECIPE_ERROR_MESSAGE = (
    "\nUnable to parse provided recipe directory or package file.\n\n"
    f"Please make sure this argument is either a valid package \n"
    f'file ({" or ".join(CONDA_PACKAGE_EXTENSIONS)}) or points to a directory containing recipe.'
)


def validate_is_conda_pkg_or_recipe_dir(arg_val: str) -> str:
    """
    Makes sure the argument is either a conda pkg file or a recipe directory.
    """
    if os.path.isdir(arg_val):
        return arg_val
    elif utils.is_conda_pkg(arg_val):
        return arg_val
    else:
        raise ArgumentError(None, CONDA_PKG_OR_RECIPE_ERROR_MESSAGE)
