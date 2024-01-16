# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from conda.core.prefix_data import PrefixData

from conda_build.inspect_pkg import which_package


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
    assert set(precs_hardlinkA) == {precA}

    precs_shared = list(which_package(tmp_path / "shared", tmp_path))
    assert len(precs_shared) == 2
    assert set(precs_shared) == {precA, precB}

    precs_internal = list(which_package(tmp_path / "internal", tmp_path))
    assert len(precs_internal) == 1
    assert set(precs_internal) == {precA}

    precs_external = list(which_package(tmp_path / "external", tmp_path))
    assert len(precs_external) == 1
    assert set(precs_external) == {precA}

    precs_hardlinkB = list(which_package(tmp_path / "hardlinkB", tmp_path))
    assert len(precs_hardlinkB) == 1
    assert set(precs_hardlinkB) == {precB}


@pytest.mark.benchmark
def test_which_package_battery(tmp_path: Path):
    # regression: https://github.com/conda/conda-build/issues/5126
    # create a dummy environment
    (tmp_path / "conda-meta").mkdir()
    (tmp_path / "conda-meta" / "history").touch()
    (tmp_path / "lib").mkdir()

    # dummy packages with files
    removed = []
    for _ in range(100):
        name = f"package_{uuid4().hex}"

        # mock a package with 100 files
        files = [f"lib/{uuid4().hex}" for _ in range(100)]
        for file in files:
            (tmp_path / file).touch()

        # mock a removed file
        remove = f"lib/{uuid4().hex}"
        files.append(remove)
        removed.append(remove)

        (tmp_path / "conda-meta" / f"{name}-1-0.json").write_text(
            json.dumps(
                {
                    "build": "0",
                    "build_number": 0,
                    "channel": f"{name}-channel",
                    "files": files,
                    "name": name,
                    "paths_data": {
                        "paths": [
                            {"_path": file, "path_type": "hardlink", "size_in_bytes": 0}
                            for file in files
                        ],
                        "paths_version": 1,
                    },
                    "version": "1",
                }
            )
        )

    # every path should return exactly one package
    for subdir, _, files in os.walk(tmp_path / "lib"):
        for file in files:
            path = Path(subdir, file)

            assert len(list(which_package(path, tmp_path))) == 1

    # removed files should return no packages
    # this occurs when, e.g., a package removes files installed by another package
    for file in removed:
        assert not len(list(which_package(tmp_path / file, tmp_path)))

    # missing files should return no packages
    assert not len(list(which_package(tmp_path / "missing", tmp_path)))


def test_which_package_reuse_env(tmp_path: Path):
    # create a dummy environment
    (tmp_path / "conda-meta").mkdir()
    (tmp_path / "conda-meta" / "history").touch()

    # "install" a dummy package
    (tmp_path / "fileA").touch()
    (tmp_path / "conda-meta" / "packageA-1-0.json").write_text(
        json.dumps(
            {
                "build": "0",
                "build_number": 0,
                "channel": "packageA-channel",
                "files": ["fileA"],
                "name": "packageA",
                "paths_data": {
                    "paths": [
                        {"_path": "fileA", "path_type": "hardlink", "size_in_bytes": 0}
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

    # test returned package records given a path
    assert set(which_package(tmp_path / "fileA", tmp_path)) == {precA}

    # "reuse" environment, mock uninstalling
    (tmp_path / "fileA").unlink()
    (tmp_path / "conda-meta" / "packageA-1-0.json").unlink()

    # "install" another package
    (tmp_path / "fileB").touch()
    (tmp_path / "conda-meta" / "packageB-1-0.json").write_text(  # reinstall
        json.dumps(
            {
                "build": "0",
                "build_number": 0,
                "channel": "packageB-channel",
                "files": ["fileB", "fileB"],
                "name": "packageB",
                "paths_data": {
                    "paths": [
                        {"_path": "fileB", "path_type": "hardlink", "size_in_bytes": 0}
                    ],
                    "paths_version": 1,
                },
                "version": "1",
            }
        )
    )

    # fetch package records
    PrefixData._cache_.clear()
    pd = PrefixData(tmp_path)
    precB = pd.get("packageB")

    # test returned package records given a path
    assert set(which_package(tmp_path / "fileB", tmp_path)) == {precB}
