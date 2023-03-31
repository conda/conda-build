# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
from pathlib import Path

from conda.common.compat import on_win

from conda_build.os_utils.external import find_executable


def test_find_executable(testing_workdir, monkeypatch):
    search_path = []

    def touch(target, searchable=True, executable=True, alternative=False):
        path = Path(
            testing_workdir,
            "alt" if alternative else "not",
            "exec" if executable else "not",
            "search" if searchable else "not",
            target,
        )
        if on_win:
            path = path.with_suffix(".bat")
        path.parent.mkdir(parents=True, exist_ok=True)

        path.touch(0o100 if executable else 0o666)

        if searchable:
            search_path.append(str(path.parent))

        return str(path)

    touch("target", searchable=False)
    # Windows doesn't have an execute bit so this is the path found
    win_expected = touch("target", executable=False)
    touch("not_target")
    nix_expected = touch("target")
    touch("target", alternative=True)
    expected = win_expected if on_win else nix_expected

    monkeypatch.setenv("PATH", os.pathsep.join(search_path))

    assert find_executable("target") == expected
