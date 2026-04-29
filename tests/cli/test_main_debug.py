# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys
from pathlib import Path
from unittest import mock

import pytest
from pytest import CaptureFixture, MonkeyPatch

from conda_build.cli import main_build as build
from conda_build.cli import main_debug as debug
from conda_build.cli import validators as valid

from ..utils import metadata_dir


def test_main_debug_help_message(capsys: CaptureFixture, monkeypatch: MonkeyPatch):
    monkeypatch.setattr(sys, "argv", ["conda-debug", "-h"])
    help_blurb = debug.get_parser().format_help()

    with pytest.raises(SystemExit):
        debug.execute()

    captured = capsys.readouterr()
    assert help_blurb in captured.out


def test_main_debug_file_does_not_exist(
    capsys: CaptureFixture, monkeypatch: MonkeyPatch
):
    monkeypatch.setattr(sys, "argv", ["conda-debug", "file-does-not-exist"])

    with pytest.raises(SystemExit):
        debug.execute()

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
        debug.execute()

        captured = capsys.readouterr()
        assert captured.err == ""

        assert len(mock_debug.mock_calls) == 2


def test_debug_v1_recipe(capsys: CaptureFixture):
    """
    Test conda-debug functionality for v1 recipe. The test uses a multi-output recipe.
    """
    recipe_dir = os.path.join(
        metadata_dir, "..", "variants", "33_v1_recipe_multi_output"
    )

    # Make sure that it fails with the expected message if output is not specified
    args = [recipe_dir]
    with pytest.raises(
        Exception, match=r"Multiple outputs found in recipe \(2\).*--output-id"
    ):
        debug.execute(args)

    # Setup scripts for the first output
    args = [recipe_dir, "--output-id", "myproject-lib"]
    assert debug.execute(args) == 0

    captured = capsys.readouterr()
    output = captured.out
    assert "myproject-lib" in output
    assert "To run the actual build, use:" in output
    assert f"conda build {recipe_dir}"

    # Setup scripts for the second output
    # Build the recipe because second output depends on the first one
    args = [recipe_dir]
    build.execute(args)

    args = [recipe_dir, "--output-id", "myproject-tools"]
    assert debug.execute(args) == 0

    captured = capsys.readouterr()
    output = captured.out
    assert "myproject-tools" in output
    assert "To run the actual build, use:" in output
    assert f"conda build {recipe_dir}"
