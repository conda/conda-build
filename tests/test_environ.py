# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import platform

import pytest

from conda_build.config import Config
from conda_build.environ import create_env, get_py_ver, os_vars

on_linux = platform.system() == "Linux"


def test_environment_creation_preserves_PATH(testing_workdir, testing_config):
    ref_path = os.environ["PATH"]
    create_env(
        testing_workdir,
        ["python"],
        env="host",
        config=testing_config,
        subdir=testing_config.build_subdir,
    )
    assert os.environ["PATH"] == ref_path


@pytest.mark.skipif(
    not on_linux, reason="BUILD variable with cdt_name is Linux-specific"
)
def test_build_variable_respects_cdt_name_variant(testing_metadata):
    """Test that BUILD environment variable uses cdt_name from variant when specified.

    This addresses issue #5733 where BUILD was hardcoded to cos6/cos7 based on
    architecture instead of respecting the cdt_name variant.
    """
    testing_metadata.config.variant["cdt_name"] = "el8"
    env_vars = os_vars(testing_metadata, testing_metadata.config.host_prefix)

    # Verify BUILD contains the cdt_name from variant
    assert "conda_el8" in env_vars["BUILD"]


@pytest.mark.skipif(
    not on_linux, reason="BUILD variable with cdt_name is Linux-specific"
)
def test_build_variable_defaults_to_architecture_based_distro(testing_metadata):
    """Test that BUILD variable defaults to cos6/cos7 when cdt_name is not specified."""
    if "cdt_name" in testing_metadata.config.variant:
        del testing_metadata.config.variant["cdt_name"]

    env_vars = os_vars(testing_metadata, testing_metadata.config.host_prefix)

    # Verify BUILD uses default cos6 or cos7 (not a custom cdt_name)
    assert "conda_cos6" in env_vars["BUILD"] or "conda_cos7" in env_vars["BUILD"]


def test_get_py_ver_normal():
    config = Config(variant={"python": "3.13"})
    ver = get_py_ver(config)
    assert ver == "3.13"
    assert not ver.endswith("t")


def test_get_py_ver_freethreading():
    config = Config(variant={"python": "3.13", "is_freethreading": True})
    ver = get_py_ver(config)
    assert ver == "3.13t"


def test_get_py_ver_freethreading_no_double_t():
    config = Config(variant={"python": "3.13t", "is_freethreading": True})
    ver = get_py_ver(config)
    assert ver == "3.13t"
