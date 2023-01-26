# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import pytest

from conda_build.api import build

from .utils import dll_dir


@pytest.mark.sanity
def test_recipe_build(testing_config, monkeypatch):
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    testing_config.activate = True
    monkeypatch.setenv("CONDA_TEST_VAR", "conda_test")
    monkeypatch.setenv("CONDA_TEST_VAR_2", "conda_test_2")
    build(dll_dir, config=testing_config)
