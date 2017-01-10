import os
import subprocess

import pytest

from conda_build import api
from .utils import testing_workdir, test_config, metadata_dir, is_valid_dir, check_call_env

published_examples = os.path.join(os.path.dirname(metadata_dir), 'published_code')


def test_skeleton_pypi(testing_workdir):
    """published in docs at http://conda.pydata.org/docs/build_tutorials/pkgs.html"""
    cmd = 'conda skeleton pypi pyinstrument'
    check_call_env(cmd.split())
    cmd = 'conda build pyinstrument'
    check_call_env(cmd.split())

@pytest.fixture(params=[dirname for dirname in os.listdir(published_examples)
                        if is_valid_dir(published_examples, dirname)])
def recipe(request):
    return os.path.join(published_examples, request.param)


# This tests any of the folders in the test-recipes/published_code folder that don't start with _
def test_recipe_builds(recipe, test_config, testing_workdir):
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    ok_to_test = api.build(recipe, config=test_config)
    if ok_to_test:
        api.test(recipe, config=test_config)
