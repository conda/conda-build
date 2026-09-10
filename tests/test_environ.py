# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import platform
from typing import TYPE_CHECKING

import pytest
from conda.base.context import context, reset_context
from conda.core.index import Index
from conda.exceptions import PackagesNotFoundError, ResolvePackageNotFound

from conda_build.environ import _install_actions, create_env, os_vars

if TYPE_CHECKING:
    from typing import Any

    from pytest import MonkeyPatch

    from conda_build.metadata import MetaData


on_linux = platform.system() == "Linux"


@pytest.mark.parametrize(
    "cached_solver, requested_solver, expected_error",
    [
        ("classic", "libmamba", PackagesNotFoundError),
        ("libmamba", "classic", ResolvePackageNotFound),
    ],
)
def test_install_actions_respects_changed_solver(
    empty_channel,
    tmp_path,
    monkeypatch,
    cached_solver,
    requested_solver,
    expected_error,
):
    cached_backend = context.plugin_manager.get_cached_solver_backend
    cached_backend.cache_clear()
    try:
        with monkeypatch.context() as patch:
            patch.setenv("CONDA_SOLVER", cached_solver)
            reset_context()
            cached_backend()

            patch.setenv("CONDA_SOLVER", requested_solver)
            reset_context()
            index = Index(
                channels=[empty_channel.as_uri()],
                prepend=False,
                platform=context.subdir,
                use_system=True,
            )
            with pytest.raises(expected_error):
                _install_actions(
                    str(tmp_path / "prefix"),
                    index,
                    ["conda_build_missing_test_requirement"],
                    subdir=context.subdir,
                )
    finally:
        cached_backend.cache_clear()
        reset_context()


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


@pytest.mark.parametrize("value", [None, "", "/path/to/ca.pem"])
def test_requests_ca_bundle_only_inherited_when_set(
    testing_metadata: MetaData,
    monkeypatch: MonkeyPatch,
    value: Any,
):
    """REQUESTS_CA_BUNDLE is omitted when unset or empty, passed through otherwise (#6063)."""
    if value is None:
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    else:
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", value)

    env_vars = os_vars(testing_metadata, testing_metadata.config.host_prefix)

    if value:
        assert env_vars["REQUESTS_CA_BUNDLE"] == value
    else:
        assert "REQUESTS_CA_BUNDLE" not in env_vars


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
