# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import sys
from pathlib import Path
from unittest import mock

import pytest
from pytest import CaptureFixture, MonkeyPatch

from conda_build.cli import main_debug as debug
from conda_build.cli import validators as valid


def test_main_debug_help_message(capsys: CaptureFixture, monkeypatch: MonkeyPatch):
    monkeypatch.setattr(sys, "argv", ["conda-debug", "-h"])
    help_blurb = debug.get_parser().format_help()

    with pytest.raises(SystemExit):
        debug.main()

    captured = capsys.readouterr()
    assert help_blurb in captured.out


def test_main_debug_file_does_not_exist(
    capsys: CaptureFixture, monkeypatch: MonkeyPatch
):
    monkeypatch.setattr(sys, "argv", ["conda-debug", "file-does-not-exist"])

    with pytest.raises(SystemExit):
        debug.main()

    captured = capsys.readouterr()
    assert valid.CONDA_PKG_OR_RECIPE_ERROR_MESSAGE in captured.err


def test_main_debug_happy_path(
    tmp_path: Path, capsys: CaptureFixture, monkeypatch: MonkeyPatch
):
    """
    Happy path through the main_debug.main function.
    """
    fake = tmp_path / "fake-conda-pkg.conda"
    fake.touch()
    monkeypatch.setattr(sys, "argv", ["conda-debug", str(fake)])

    with mock.patch("conda_build.api.debug") as mock_debug:
        debug.main()

        captured = capsys.readouterr()
        assert captured.err == ""

        assert len(mock_debug.mock_calls) == 2
