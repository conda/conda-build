import os

import pytest

from conda_build import api
from conda_build.utils import check_call_env
from .utils import metadata_dir, is_valid_dir

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
def test_recipe_builds(recipe, testing_config, testing_workdir):
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    api.build(recipe, config=testing_config)
