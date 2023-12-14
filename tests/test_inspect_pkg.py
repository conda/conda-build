# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import json
from pathlib import Path

import pytest
from conda import __version__ as conda_version
from conda.core.prefix_data import PrefixData
from packaging.version import Version, parse

from conda_build.inspect_pkg import which_package


@pytest.mark.skipif(
    parse(conda_version) < Version("23.5.0"),
    reason="tmp_env fixture first available in conda 23.5.0",
)
def test_which_package(tmp_path: Path):
    # create a dummy environment
    (tmp_path / "conda-meta").mkdir()
    (tmp_path / "conda-meta" / "history").touch()
    # a dummy package with a unique file (softlink) and a shared file (shared)
    (tmp_path / "conda-meta" / "packageA-1-0.json").write_text(
        json.dumps(
            {
                "build": "0",
                "build_number": 0,
                "channel": "packageA-channel",
                "files": ["softlink", "shared"],
                "name": "packageA",
                "paths_data": {
                    "paths": [
                        {
                            "_path": "softlink",
                            "path_type": "softlink",
                            "size_in_bytes": 0,
                        },
                        {
                            "_path": "shared",
                            "path_type": "hardlink",
                            "size_in_bytes": 0,
                        },
                    ],
                    "paths_version": 1,
                },
                "version": "1",
            }
        )
    )
    # a dummy package with a unique file (hardlink) and a shared file (shared)
    (tmp_path / "conda-meta" / "packageB-1-0.json").write_text(
        json.dumps(
            {
                "build": "0",
                "build_number": 0,
                "channel": "packageB-channel",
                "files": ["hardlink", "shared"],
                "name": "packageB",
                "paths_data": {
                    "paths": [
                        {
                            "_path": "hardlink",
                            "path_type": "hardlink",
                            "size_in_bytes": 0,
                        },
                        {
                            "_path": "shared",
                            "path_type": "hardlink",
                            "size_in_bytes": 0,
                        },
                    ],
                    "paths_version": 1,
                },
                "version": "1",
            }
        )
    )

    # fetch package records
    pd = PrefixData(tmp_path)
    precA = pd.get("packageA")
    precB = pd.get("packageB")

    # test returned package records given a path
    precs_missing = list(which_package(tmp_path / "missing", tmp_path))
    assert not precs_missing

    precs_softlink = list(which_package(tmp_path / "softlink", tmp_path))
    assert len(precs_softlink) == 1
    assert precs_softlink[0] == precA

    precs_hardlink = list(which_package(tmp_path / "hardlink", tmp_path))
    assert len(precs_hardlink) == 1
    assert precs_hardlink[0] == precB

    precs_shared = list(which_package(tmp_path / "shared", tmp_path))
    assert len(precs_shared) == 2
    assert set(precs_shared) == {precA, precB}
