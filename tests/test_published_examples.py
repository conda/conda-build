import os

import pytest

import sys

from conda_build import api
from conda_build.utils import check_call_env
from .utils import metadata_dir, is_valid_dir

published_examples = os.path.join(os.path.dirname(metadata_dir), 'published_code')


@pytest.mark.sanity
def test_skeleton_pypi(testing_workdir):
    """published in docs at http://conda.pydata.org/docs/build_tutorials/pkgs.html"""
    conda_path = os.path.join(sys.prefix, 'Scripts' if sys.platform == 'win32' else 'bin', 'conda')
    cmd = conda_path + ' skeleton pypi Click'
    check_call_env(cmd.split())
    cmd = conda_path + ' build click'
    check_call_env(cmd.split())


@pytest.fixture(params=[dirname for dirname in os.listdir(published_examples)
                        if is_valid_dir(published_examples, dirname)])
def recipe(request):
    return os.path.join(published_examples, request.param)


# This tests any of the folders in the test-recipes/published_code folder that don't start with _
@pytest.mark.sanity
def test_recipe_builds(recipe, testing_config, testing_workdir):
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    api.build(recipe, config=testing_config)
