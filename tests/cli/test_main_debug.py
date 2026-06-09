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
from conda_build.exceptions import CondaBuildUserError
from conda_build.utils import on_win

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
        CondaBuildUserError,
        match=r"Found 2 outputs in recipe. Please specify one using --output-id.",
    ):
        debug.execute(args)

    # Setup scripts for the first output
    args = [recipe_dir, "--output-id", "myproject-lib"]
    assert debug.execute(args) == 0

    captured = capsys.readouterr()
    output = captured.out
    assert "Test environment created for debugging." in output
    assert "rattler-build_myproject-lib" in output
    expected = (
        "To run your tests, you might want to start with running the conda_build.bat file."
        if on_win
        else "To run your tests, you might want to start with running the conda_build.sh file."
    )
    assert expected in output

    # Setup scripts for the second output
    # Build the recipe because second output depends on the first one
    args = [recipe_dir]
    build.execute(args)

    args = [recipe_dir, "--output-id", "myproject-tools"]
    assert debug.execute(args) == 0

    captured = capsys.readouterr()
    output = captured.out
    assert "Test environment created for debugging." in output
    assert "rattler-build_myproject-tools" in output
    assert expected in output


def test_error_if_package_contains_recipe_yaml(tmp_path: Path, capsys: CaptureFixture):
    recipe_dir = Path(metadata_dir, "..", "variants", "32_v1_recipe")
    out = tmp_path / "out"

    args = [
        str(recipe_dir),
        "-c",
        "conda-forge",
        "--no-test",
        "--output-folder",
        str(out),
    ]
    build.execute(args)

    pkg_files = list((out / "noarch").glob("pytest*.conda"))
    assert len(pkg_files) == 1, pkg_files
    pkg_file = pkg_files[0]

    with pytest.raises(SystemExit) as exc:
        debug.execute([str(pkg_file)])

    assert exc.value.code == 1

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert (
        "contains v1 'recipe.yaml' file, which is currently not supported by conda debug."
        in output
    )
