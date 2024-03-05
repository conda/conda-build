# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os

import pytest

from conda_build import api

from .utils import metadata_dir


@pytest.mark.parametrize("pkg_format,pkg_ext", [(None, ".tar.bz2"), ("2", ".conda")])
def test_conda_pkg_format(
    pkg_format, pkg_ext, testing_config, monkeypatch, capfd, request
):
    """Conda package format "2" builds .conda packages."""

    # Build the "entry_points" recipe, which contains a test pass for package.
    recipe = os.path.join(metadata_dir, "entry_points")

    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    testing_config.activate = True
    testing_config.conda_pkg_format = pkg_format
    monkeypatch.setenv("CONDA_TEST_VAR", "conda_test")
    monkeypatch.setenv("CONDA_TEST_VAR_2", "conda_test_2")

    # Recipe "entry_points" is used in other test -> add test-specific variant
    # (change build hash) to avoid clashes in package cache from other tests.
    variants = {"pytest_name": [request.node.name]}
    (output_file,) = api.get_output_file_paths(
        recipe, config=testing_config, variants=variants
    )
    assert output_file.endswith(pkg_ext)

    api.build(recipe, config=testing_config, variants=variants)
    assert os.path.exists(output_file)

    out, err = capfd.readouterr()

    # Verify that test pass ran through api
    assert "Manual entry point" in out
    assert "TEST END: %s" % output_file in out
