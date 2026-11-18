# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""Tests for `.condarc` validation when building v1 (rattler-build) recipes."""

from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

# `compat` (and `main_build`, which imports it) require rattler_build
pytest.importorskip("rattler_build")

from conda_build._rattler_build import compat  # noqa: E402
from conda_build.cli import main_build  # noqa: E402

if TYPE_CHECKING:
    from pytest import MonkeyPatch


def _set_condarc(monkeypatch: MonkeyPatch, condarc: dict) -> None:
    """Replace the `context` seen by `compat` with one exposing `condarc`."""
    monkeypatch.setattr(compat, "context", SimpleNamespace(conda_build=condarc))


def _check(monkeypatch: MonkeyPatch, condarc: dict, command: str = "build") -> None:
    """Run the condarc validation using only the recipe as a CLI argument."""
    _set_condarc(monkeypatch, condarc)
    parsed = Namespace(recipe=["recipe"])
    compat.check_arguments_rattler(command, parsed, parsed)


def test_condarc_only_keys_contains_pkg_format():
    assert "pkg_format" in compat.CONDARC_ONLY_KEYS


def test_condarc_only_keys_do_not_overlap_cli_args():
    """Keys that are valid CLI dests don't belong in the condarc-only allowlist.

    `pkg_format` differs from the `conda_pkg_format` dest, which is the reason
    it needs an explicit allowlist entry.
    """
    _, parsed = main_build.parse_args(["recipe"])
    assert not compat.CONDARC_ONLY_KEYS & set(vars(parsed))


@pytest.mark.parametrize("value", ["1", "2", ".tar.bz2", ".conda", 1, 2])
def test_pkg_format_condarc_is_accepted(monkeypatch: MonkeyPatch, value):
    # must not raise
    _check(monkeypatch, {"pkg_format": value})


@pytest.mark.parametrize("command", ["build", "render", "debug"])
def test_pkg_format_condarc_is_accepted_for_every_command(
    monkeypatch: MonkeyPatch, command: str
):
    # the condarc check is applied against the union of all commands' keys
    _check(monkeypatch, {"pkg_format": "2"}, command=command)


def test_empty_condarc_is_accepted(monkeypatch: MonkeyPatch):
    _check(monkeypatch, {})


def test_supported_condarc_keys_still_accepted(monkeypatch: MonkeyPatch):
    _check(monkeypatch, {"skip_existing": "true", "output_folder": "/tmp/out"})


def test_supported_condarc_keys_accepted_alongside_pkg_format(
    monkeypatch: MonkeyPatch,
):
    _check(monkeypatch, {"pkg_format": "2", "skip_existing": "true", "croot": "/c"})


def test_unsupported_condarc_key_still_rejected(monkeypatch: MonkeyPatch):
    with pytest.raises(ValueError, match="Invalid condarc settings.*activate"):
        _check(monkeypatch, {"activate": "false"})


def test_unsupported_condarc_key_rejected_next_to_pkg_format(
    monkeypatch: MonkeyPatch,
):
    with pytest.raises(ValueError, match="Invalid condarc settings") as exc_info:
        _check(monkeypatch, {"pkg_format": "2", "activate": "false"})

    # only the genuinely unsupported key is reported, never `pkg_format`
    message = str(exc_info.value)
    assert "activate" in message
    assert "pkg_format" not in message


def test_multiple_unsupported_condarc_keys_reported_sorted(monkeypatch: MonkeyPatch):
    with pytest.raises(ValueError, match="Invalid condarc settings") as exc_info:
        _check(monkeypatch, {"zzz_bad": 1, "pkg_format": "2", "aaa_bad": 2})

    message = str(exc_info.value)
    assert message.endswith("aaa_bad, zzz_bad")
    assert "pkg_format" not in message


def test_condarc_error_names_the_command(monkeypatch: MonkeyPatch):
    with pytest.raises(ValueError, match="conda-render"):
        _check(monkeypatch, {"activate": "false"}, command="render")


def test_cli_args_validated_before_condarc(monkeypatch: MonkeyPatch):
    """An unsupported CLI argument is reported even when condarc is fine."""
    _set_condarc(monkeypatch, {"pkg_format": "2"})
    only_recipe = Namespace(recipe=["recipe"])
    parsed = Namespace(recipe=["recipe"], no_such_flag=True)
    with pytest.raises(ValueError, match="Invalid arguments for conda-build"):
        compat.check_arguments_rattler("build", parsed, only_recipe)


def test_pkg_format_condarc_with_real_cli_parser(monkeypatch: MonkeyPatch):
    """Validate using the real argparse namespaces that `conda build` produces."""
    _set_condarc(monkeypatch, {"pkg_format": "2"})

    _, parsed = main_build.parse_args(["recipe"])
    _, parsed_only_recipe = main_build.parse_args(["recipe"])

    # must not raise
    compat.check_arguments_rattler("build", parsed, parsed_only_recipe)
