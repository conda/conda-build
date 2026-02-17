# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys

import pytest

from conda_build import api
from conda_build.cli import main_build, main_skeleton


@pytest.mark.sanity
def test_skeleton_pypi(testing_workdir, testing_config):
    args = ["pypi", "peppercorn"]
    main_skeleton.execute(args)
    assert os.path.isdir("peppercorn")

    # ensure that recipe generated is buildable
    main_build.execute(("peppercorn",))


@pytest.mark.sanity
def test_skeleton_pypi_compatible_versions(testing_workdir, testing_config):
    args = ["pypi", "openshift"]
    main_skeleton.execute(args)
    assert os.path.isdir("openshift")


@pytest.mark.slow
def test_skeleton_pypi_arguments_work(testing_workdir):
    """
    These checks whether skeleton executes without error when these
    options are specified on the command line AND whether the underlying
    functionality works as a regression test for:

    https://github.com/conda/conda-build/pull/1384
    """
    args = ["pypi", "fasttext", "--version=0.9.2", "--pin-numpy"]
    main_skeleton.execute(args)
    assert os.path.isdir("fasttext")

    # Deliberately bypass metadata reading in conda build to get as
    # close to the "ground truth" as possible.
    with open(os.path.join("fasttext", "meta.yaml")) as f:
        assert f.read().count("numpy x.x") == 2

    args = [
        "pypi",
        "photutils",
        "--version=1.10.0",
        "--setup-options=--offline",
        "--extra-specs=extension-helpers",
    ]
    main_skeleton.execute(args)
    assert os.path.isdir("photutils")
    # Check that the setup option occurs in bld.bat and build.sh.

    metadata = api.render("photutils")[0][0]
    assert "--offline" in metadata.meta["build"]["script"]
    assert metadata.version() == "1.10.0"


@pytest.mark.slow
@pytest.mark.skipif(sys.version_info < (3, 11), reason="requires python3.11 or higher")
def test_v1_recipe_generation(testing_workdir):
    """
    Test v1 recipe generation
    """
    args = ["--output-format=v1", "pypi", "botocore"]
    main_skeleton.execute(args)
    assert os.path.isfile("botocore/recipe.yaml")
    with open(os.path.join("botocore", "recipe.yaml")) as f:
        assert "botocore" in f.read()
