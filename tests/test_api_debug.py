# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
This module tests the test API.  These are high-level integration tests.  Lower level unit tests
should go in test_render.py
"""
from __future__ import annotations

import subprocess
from contextlib import nullcontext
from pathlib import Path

import pytest
from conda.common.compat import on_win

from conda_build.api import debug

from .utils import archive_path, metadata_path

DEBUG_PKG = metadata_path / "_debug_pkg"
MULTI_OUT = metadata_path / "_debug_pkg_multiple_outputs"
TARBALL = archive_path / "test_debug_pkg-1.0-0.tar.bz2"
SHELL_CMD = ("cmd.exe", "/d", "/c") if on_win else ("bash", "-c")


@pytest.mark.parametrize(
    "recipe,path,config,output_id,has_error,has_build",
    [
        # w/ config
        pytest.param(DEBUG_PKG, False, True, None, False, True, id="recipe w/ config"),
        pytest.param(TARBALL, False, True, None, False, False, id="tarball w/ config"),
        # w/ path
        pytest.param(DEBUG_PKG, True, False, None, False, True, id="recipe w/ path"),
        pytest.param(TARBALL, True, False, None, False, False, id="tarball w/ path"),
        # w/ outputs
        pytest.param(
            MULTI_OUT,
            False,
            False,
            "output1*",
            False,
            True,
            id="outputs w/ valid filtering",
        ),
        pytest.param(
            MULTI_OUT,
            False,
            False,
            None,
            True,
            False,
            id="outputs w/ no filtering",
        ),
        pytest.param(
            MULTI_OUT,
            False,
            False,
            "frank",
            True,
            False,
            id="outputs w/ invalid filtering",
        ),
    ],
)
def test_debug(
    recipe: Path,
    path: bool,
    config: bool,
    output_id: str | None,
    has_error: bool,
    has_build: bool,
    tmp_path: Path,
    testing_config,
):
    with pytest.raises(ValueError) if has_error else nullcontext():
        activation = debug(
            str(recipe),
            path=tmp_path if path else None,
            config=testing_config if config else None,
            output_id=output_id,
        )

    # if we expected an error there wont be anything else to test
    if has_error:
        return

    # e.g.: activation = "cd /path/to/work && source /path/to/work/build_env_setup.sh"
    _, work_dir, _, source, script = activation.split()
    work_path = Path(work_dir)

    # recipes and tarballs are installed into different locations
    if recipe.suffixes[-2:] == [".tar", ".bz2"]:
        assert work_path.name == "test_tmp"
    elif path:
        assert work_path.parent == tmp_path
    else:
        assert work_path.parent.name.startswith("debug_")

    # check build files are present
    name = "bld.bat" if on_win else "conda_build.sh"
    assert (work_path / name).exists() is has_build
    for prefix in ("_b*", "_h*"):
        assert bool(next(work_path.parent.glob(prefix), False)) is has_build

    # check test files are present
    name = f"conda_test_runner{('.bat' if on_win else '.sh')}"
    has_test = not has_build
    assert (work_path / name).exists() is has_test
    for prefix in ("_t*", "test_tmp"):
        assert bool(next(work_path.parent.glob(prefix), False)) is has_test

    # ensure it's possible to activate the environment
    subprocess.check_call([*SHELL_CMD, f"{source} {script}"], cwd=work_path)
