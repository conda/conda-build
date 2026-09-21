# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import platform
from typing import TYPE_CHECKING

import pytest
from conda.base.context import context
from conda.core.index import Index
from conda.core.subdir_data import SubdirData
from conda.models.match_spec import MatchSpec
from conda.models.records import PackageRecord

from conda_build.environ import _install_actions, create_env, os_vars

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from pytest import MonkeyPatch
    from pytest_mock import MockerFixture

    from conda_build.metadata import MetaData


on_linux = platform.system() == "Linux"


@pytest.mark.parametrize("realized", [False, True], ids=["lazy", "realized"])
def test_install_actions_copies_index(
    tmp_path: Path, mocker: MockerFixture, realized: bool
):
    prefix = str(tmp_path)
    record = PackageRecord(name="test", version="1", build="0", build_number=0)
    index = Index(
        channels=("https://example.org/channel",),
        prepend=False,
        subdirs=("linux-64", "noarch"),
        use_cache=False,
    )
    if realized:
        mocker.patch.object(
            SubdirData, "iter_records", side_effect=lambda: iter((record,))
        )
        assert index.data == {record: record}
    else:
        mocker.patch.object(
            Index,
            "data",
            new_callable=mocker.PropertyMock,
            side_effect=AssertionError("The lazy index must not access Index.data"),
        )

    solver = mocker.Mock()
    solver.solve_for_transaction.return_value.prefix_setups = {
        prefix: mocker.Mock(link_precs=(record,))
    }
    backend = mocker.Mock(return_value=solver)
    mocker.patch.object(
        context.plugin_manager, "get_cached_solver_backend", return_value=backend
    )

    actions = _install_actions(prefix, index, ("test >=1",), subdir="linux-64")

    backend.assert_called_once_with(
        prefix,
        tuple(index.expanded_channels),
        tuple(index._subdirs),
        specs_to_add=(MatchSpec("test >=1"),),
    )
    solver.solve_for_transaction.assert_called_once_with(
        prune=False, ignore_pinned=False
    )
    assert actions == {"PREFIX": prefix, "LINK": [record]}
    assert isinstance(solver._index, Index)
    assert solver._index is not index
    if realized:
        assert solver._index.data == index.data
        solver._index.clear()
        assert index.data == {record: record}
    else:
        assert "_data" not in index.__dict__
        assert "_data" not in solver._index.__dict__


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
