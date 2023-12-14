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

    # dummy files
    (tmp_path / "hardlinkA").touch()  # packageA
    (tmp_path / "shared").touch()  # packageA & packageB
    (tmp_path / "internal").symlink_to(tmp_path / "hardlinkA")  # packageA
    (tmp_path / "external").symlink_to(tmp_path / "hardlinkB")  # packageA
    (tmp_path / "hardlinkB").touch()  # packageB

    # a dummy package with a hardlink file, shared file, internal softlink, and external softlink
    (tmp_path / "conda-meta" / "packageA-1-0.json").write_text(
        json.dumps(
            {
                "build": "0",
                "build_number": 0,
                "channel": "packageA-channel",
                "files": ["hardlinkA", "shared", "internal", "external"],
                "name": "packageA",
                "paths_data": {
                    "paths": [
                        {
                            "_path": "hardlinkA",
                            "path_type": "hardlink",
                            "size_in_bytes": 0,
                        },
                        {
                            "_path": "shared",
                            "path_type": "hardlink",
                            "size_in_bytes": 0,
                        },
                        {
                            "_path": "internal",
                            "path_type": "softlink",
                            "size_in_bytes": 0,
                        },
                        {
                            "_path": "external",
                            "path_type": "softlink",
                            "size_in_bytes": 0,
                        },
                    ],
                    "paths_version": 1,
                },
                "version": "1",
            }
        )
    )
    # a dummy package with a hardlink file and shared file
    (tmp_path / "conda-meta" / "packageB-1-0.json").write_text(
        json.dumps(
            {
                "build": "0",
                "build_number": 0,
                "channel": "packageB-channel",
                "files": ["hardlinkB", "shared"],
                "name": "packageB",
                "paths_data": {
                    "paths": [
                        {
                            "_path": "hardlinkB",
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

    precs_hardlinkA = list(which_package(tmp_path / "hardlinkA", tmp_path))
    assert len(precs_hardlinkA) == 1
    assert precs_hardlinkA[0] == precA

    precs_shared = list(which_package(tmp_path / "shared", tmp_path))
    assert len(precs_shared) == 2
    assert set(precs_shared) == {precA, precB}

    precs_internal = list(which_package(tmp_path / "internal", tmp_path))
    assert len(precs_internal) == 1
    assert precs_internal[0] == precA

    precs_external = list(which_package(tmp_path / "external", tmp_path))
    assert len(precs_external) == 2
    assert set(precs_external) == {precA, precB}

    precs_hardlinkB = list(which_package(tmp_path / "hardlinkB", tmp_path))
    assert len(precs_hardlinkB) == 2
    assert set(precs_hardlinkB) == {precA, precB}
