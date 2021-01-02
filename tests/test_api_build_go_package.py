import os
import pytest

from conda_build import api

from .utils import thisdir

@pytest.fixture()
def recipe():
    return os.path.join(thisdir, 'test-recipes', 'go-package')

@pytest.mark.sanity
@pytest.mark.serial
def test_recipe_build(recipe, testing_config, testing_workdir, monkeypatch):
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    testing_config.activate = True
    monkeypatch.setenv("CONDA_TEST_VAR", "conda_test")
    monkeypatch.setenv("CONDA_TEST_VAR_2", "conda_test_2")
    api.build(recipe, config=testing_config)


