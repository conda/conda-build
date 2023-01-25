# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys

import pytest

from conda.testing.integration import BIN_DIRECTORY
from conda_build.api import build
from conda_build.utils import check_call_env
from .utils import published_path, get_valid_recipes


@pytest.mark.sanity
def test_skeleton_pypi():
    """published in docs at https://docs.conda.io/projects/conda-build/en/latest/user-guide/tutorials/build-pkgs-skeleton.html"""
    conda_path = os.path.join(sys.prefix, BIN_DIRECTORY, "conda")

    check_call_env([conda_path, "skeleton", "pypi", "click"])
    check_call_env([conda_path, "build", "click"])


@pytest.mark.sanity
@pytest.mark.parametrize("recipe", get_valid_recipes(published_path))
def test_recipe_builds(recipe, testing_config):
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    build(str(recipe), config=testing_config)
