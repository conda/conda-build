import os
import pytest

from conda_build import api

from .utils import thisdir


@pytest.fixture()
def recipe():
    return os.path.join(thisdir, 'test-recipes', 'virtual-req')


@pytest.mark.sanity
def test_recipe_build(recipe, testing_config, testing_workdir, monkeypatch):
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    api.build(recipe, config=testing_config)


