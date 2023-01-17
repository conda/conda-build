# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys

import pytest

from conda_build.api import build
from conda_build.utils import check_call_env
from .utils import published_dir, is_valid_dir


@pytest.mark.sanity
def test_skeleton_pypi(testing_workdir):
    """published in docs at https://docs.conda.io/projects/conda-build/en/latest/user-guide/tutorials/build-pkgs-skeleton.html"""
    conda_path = os.path.join(sys.prefix, 'Scripts' if sys.platform == 'win32' else 'bin', 'conda')
    cmd = conda_path + ' skeleton pypi click'
    check_call_env(cmd.split())
    cmd = conda_path + ' build click'
    check_call_env(cmd.split())


@pytest.mark.sanity
@pytest.mark.parametrize(
    "recipe",
    [
        os.path.join(published_dir, dirname)
        for dirname in os.listdir(published_dir)
        # tests any recipes in test-recipes/published_code that don't start with _
        if is_valid_dir(published_dir, dirname)
    ],
)
def test_recipe_builds(recipe, testing_config, testing_workdir):
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    build(recipe, config=testing_config)
