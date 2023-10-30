# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from conda_build.os_utils.liefldd import codefile_class as liefldd_codefile_class
from conda_build.os_utils.pyldd import DLLfile, EXEfile, elffile, machofile
from conda_build.os_utils.pyldd import codefile_class as pyldd_codefile_class

LDD = Path(__file__).parent.parent / "data" / "ldd"


@pytest.mark.parametrize(
    "path,expect",
    [
        pytest.param(__file__, None, id="Unknown"),
        pytest.param(LDD / "jansi.dll", DLLfile, id="DLL"),
        pytest.param(LDD / "uuid.pyd", DLLfile, id="PYD"),
        pytest.param(LDD / "clear.exe", EXEfile, id="EXE"),
        pytest.param(LDD / "clear.macho", machofile, id="MACHO"),
        pytest.param(LDD / "clear.elf", elffile, id="ELF"),
    ],
)
@pytest.mark.parametrize(
    "codefile_class",
    [
        pytest.param(pyldd_codefile_class, id="pyldd"),
        pytest.param(liefldd_codefile_class, id="liefldd"),
    ],
)
def test_codefile_class(
    path: str | Path,
    expect: type[DLLfile | EXEfile | machofile | elffile] | None,
    codefile_class: Callable,
):
    assert codefile_class(path) == expect
