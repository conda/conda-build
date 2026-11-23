# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""Tests for condarc validation when building v1 recipes."""

from __future__ import annotations

from argparse import Namespace
from typing import TYPE_CHECKING

import pytest
from conda.base.context import Context

pytest.importorskip("rattler_build")

from conda_build._rattler_build import compat
from conda_build.cli import main_build
from conda_build.config import CondaPkgFormat

if TYPE_CHECKING:
    from pytest import FixtureRequest, MonkeyPatch


@pytest.fixture
def condarc(request: FixtureRequest, monkeypatch: MonkeyPatch) -> None:
    """Give the CLI parser and validator the same isolated conda-build settings."""
    monkeypatch.setattr(Context, "conda_build", request.param)


@pytest.mark.parametrize("command", ["build", "render", "debug"])
@pytest.mark.parametrize(
    "condarc",
    [
        pytest.param({}, id="empty"),
        pytest.param({"pkg_format": "2"}, id="pkg-format"),
        pytest.param(
            {"skip_existing": "true", "output_folder": "/tmp/out"},
            id="supported-keys",
        ),
        pytest.param(
            {"pkg_format": "2", "skip_existing": "true", "croot": "/c"},
            id="pkg-format-and-supported-keys",
        ),
    ],
    indirect=["condarc"],
)
def test_supported_condarc_keys(condarc, command: str):
    parsed = Namespace(recipe=["recipe"])
    compat.check_arguments_rattler(command, parsed, parsed)


@pytest.mark.parametrize("command", ["build", "render", "debug"])
@pytest.mark.parametrize(
    "condarc, unsupported",
    [
        pytest.param({"activate": "false"}, "activate", id="unsupported-key"),
        pytest.param(
            {"pkg_format": "2", "activate": "false"},
            "activate",
            id="pkg-format-and-unsupported-key",
        ),
        pytest.param(
            {"zzz_bad": 1, "pkg_format": "2", "aaa_bad": 2},
            "aaa_bad, zzz_bad",
            id="sorted-unsupported-keys",
        ),
    ],
    indirect=["condarc"],
)
def test_unsupported_condarc_keys(condarc, command: str, unsupported: str):
    parsed = Namespace(recipe=["recipe"])
    with pytest.raises(ValueError) as exc_info:
        compat.check_arguments_rattler(command, parsed, parsed)

    assert str(exc_info.value) == (
        f"Invalid condarc settings for conda-{command}: {unsupported}"
    )


@pytest.mark.parametrize(
    "condarc", [{"pkg_format": "2", "activate": "false"}], indirect=["condarc"]
)
def test_cli_arguments_validated_before_condarc(condarc):
    parsed = Namespace(recipe=["recipe"], no_such_flag=True)
    only_recipe = Namespace(recipe=["recipe"])
    with pytest.raises(ValueError, match="Invalid arguments for conda-build"):
        compat.check_arguments_rattler("build", parsed, only_recipe)


@pytest.mark.parametrize(
    "condarc, expected",
    [
        pytest.param({"pkg_format": "1"}, CondaPkgFormat.V1, id="v1-string"),
        pytest.param({"pkg_format": "2"}, CondaPkgFormat.V2, id="v2-string"),
        pytest.param({"pkg_format": ".tar.bz2"}, CondaPkgFormat.V1, id="v1-extension"),
        pytest.param({"pkg_format": ".conda"}, CondaPkgFormat.V2, id="v2-extension"),
        pytest.param({"pkg_format": 1}, CondaPkgFormat.V1, id="v1-integer"),
        pytest.param({"pkg_format": 2}, CondaPkgFormat.V2, id="v2-integer"),
    ],
    indirect=["condarc"],
)
def test_pkg_format_condarc_with_real_cli_parser(condarc, expected: CondaPkgFormat):
    _, parsed = main_build.parse_args(["recipe"])
    _, only_recipe = main_build.parse_args(["recipe"])

    assert parsed.conda_pkg_format is expected
    compat.check_arguments_rattler("build", parsed, only_recipe)
