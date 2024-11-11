# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import stat
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from conda_build.exceptions import CondaBuildUserError
from conda_build.noarch_python import rewrite_script
from conda_build.utils import bin_dirname, on_win

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "before,after",
    [
        ("script.py", "script.py"),
        ("script-script.py", "script" if on_win else "script-script.py"),
    ],
)
def test_rewrite_script(tmp_path: Path, before: str, after: str) -> None:
    """Test that a script file is rewritten to the python-scripts directory."""
    script = tmp_path / bin_dirname / before
    script.parent.mkdir()

    # write some text to the script
    script.write_text(text := uuid4().hex)

    # change the permissions so we can check they are preserved
    script.chmod(permissions := stat.S_IFREG | (0o444 if on_win else 0o456))

    # rewrite the script to the python-scripts directory
    rewrite_script(script.name, tmp_path)

    # check that the original script has been removed
    assert not script.exists()

    # check that the script has been rewritten to the python-scripts directory,
    # has the same text, and the same permissions
    rewrite = tmp_path / "python-scripts" / after
    assert rewrite.read_text() == text
    assert rewrite.stat().st_mode == permissions


def test_rewrite_script_binary(tmp_path: Path) -> None:
    """Test that a binary file will raise an error."""
    binary = tmp_path / bin_dirname / "binary"
    binary.parent.mkdir()

    # write some binary data to the script
    binary.write_bytes(b"\x80\x81\x82\x83\x84\x85")

    # try to rewrite the binary script to the python-scripts directory
    with pytest.raises(CondaBuildUserError, match=r"package contains binary script"):
        rewrite_script(binary.name, tmp_path)
