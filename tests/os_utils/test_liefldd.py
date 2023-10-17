# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from pathlib import Path

import pytest

from conda_build.os_utils.liefldd import (
    DLLfile,
    EXEfile,
    codefile_class,
    elffile,
    machofile,
)


@pytest.mark.parametrize(
    "path,expect",
    [
        pytest.param(__file__, None, id="None"),
        pytest.param(
            Path(__file__).parent.parent / "test-recipes" / "dll-package" / "jansi.dll",
            DLLfile,
            id="DLL[.dll]",
        ),
        pytest.param(
            Path(__file__).parent.parent / "data" / "ldd" / "uuid.pyd",
            DLLfile,
            id="DLL[.pyd]",
        ),
        pytest.param(
            Path(__file__).parent.parent / "data" / "ldd" / "clear.exe",
            EXEfile,
            id="EXE",
        ),
        pytest.param(
            Path(__file__).parent.parent / "data" / "ldd" / "clear-mach-o",
            machofile,
            id="Mach-O",
        ),
        pytest.param(
            Path(__file__).parent.parent / "data" / "ldd" / "clear-elf",
            elffile,
            id="ELF",
        ),
    ],
)
def test_codefile_class(
    path: str | Path,
    expect: type[DLLfile | EXEfile | machofile | elffile] | None,
):
    assert codefile_class(path) == expect
