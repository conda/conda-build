from __future__ import annotations

import os
import sys
from argparse import ArgumentParser, Namespace
from functools import wraps
from typing import Sequence, Callable, Tuple

from conda_build.utils import CONDA_PACKAGE_EXTENSIONS
from conda_build import utils

ParserFunction = Callable[..., Tuple[ArgumentParser, Namespace]]
ValidatorFunction = Callable[[str, Namespace], str]


def validate_args(
    validators: Sequence[tuple[str, ValidatorFunction]],
    parser: ArgumentParser,
):
    """
    Runs a set of validation rules for a command. We assume that the first positional
    argument is and
    """
    def outer_wrap(func):
        @wraps(func)
        def wrapper(*args_, **kwargs):
            args = sys.argv[1:]
            cmd_args = parser.parse_args(args)

            for arg, validate in validators:
                arg_val = getattr(cmd_args, arg)
                setattr(cmd_args, arg, validate(arg_val, cmd_args))

            return func(cmd_args, *args_, **kwargs)
        return wrapper
    return outer_wrap


def get_is_conda_pkg_or_recipe_error_message() -> str:
    """Return the error displayed on the `validate_is_conda_pkg_or_recipe_dir` validator"""
    valid_ext_str = ' or '.join(CONDA_PACKAGE_EXTENSIONS)
    return (
        'Error: Unable to parse provided recipe directory or package file.\n\n'
        f'Please make sure this argument is either a valid package \n'
        f'file ({valid_ext_str}) or points to a directory containing recipe.'
    )


def validate_is_conda_pkg_or_recipe_dir(arg_val: str, _: Namespace) -> str:
    """
    Makes sure the argument is either a conda pkg file or a recipe directory.
    """
    if os.path.isdir(arg_val):
        return arg_val
    elif utils.is_conda_pkg(arg_val):
        return arg_val
    else:
        sys.stderr.write(get_is_conda_pkg_or_recipe_error_message())
        sys.exit(1)
