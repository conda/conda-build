# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import pytest

from conda_build import api

from .utils import thisdir

pytestmark = pytest.mark.usefixtures("api_default_testing_config")


@pytest.fixture()
def recipe():
    return os.path.join(thisdir, 'test-recipes', 'dll-package')


@pytest.mark.sanity
def test_recipe_build(recipe, testing_config, testing_workdir, monkeypatch):
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    testing_config.activate = True
    monkeypatch.setenv("CONDA_TEST_VAR", "conda_test")
    monkeypatch.setenv("CONDA_TEST_VAR_2", "conda_test_2")
    api.build(recipe, config=testing_config)
