# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from conda.core.prefix_data import PrefixData

from conda_build.exceptions import CondaBuildUserError
from conda_build.inspect_pkg import inspect_linkages, inspect_objects, which_package
from conda_build.utils import on_mac, on_win


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
    # Files might be deleted from the prefix during the build, but they should
    # still be recognized since they will be present in the run environment.
    (tmp_path / "deleted").unlink(missing_ok=True)  # packageA
    (tmp_path / "deleted_shared").unlink(missing_ok=True)  # packageA & packageB

    # a dummy package with a hardlink file, shared file, internal softlink,
    # external softlink, deleted file, and deleted shared file
    (tmp_path / "conda-meta" / "packageA-1-0.json").write_text(
        json.dumps(
            {
                "build": "0",
                "build_number": 0,
                "channel": "packageA-channel",
                "files": [
                    "hardlinkA",
                    "shared",
                    "internal",
                    "external",
                    "deleted",
                    "deleted_shared",
                ],
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
                        {
                            "_path": "deleted",
                            "path_type": "hardlink",
                            "size_in_bytes": 0,
                        },
                        {
                            "_path": "deleted_shared",
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
    # a dummy package with a hardlink file, shared file, and deleted shared file
    (tmp_path / "conda-meta" / "packageB-1-0.json").write_text(
        json.dumps(
            {
                "build": "0",
                "build_number": 0,
                "channel": "packageB-channel",
                "files": ["hardlinkB", "shared", "deleted_shared"],
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
                        {
                            "_path": "deleted_shared",
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

    precs_Hardlinka = list(which_package(tmp_path / "Hardlinka", tmp_path))
    if on_win:
        # On Windows, be lenient and allow case-insensitive path comparisons.
        assert len(precs_Hardlinka) == 1
        assert set(precs_Hardlinka) == {precA}
    else:
        assert not precs_Hardlinka

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

    precs_deleted = list(which_package(tmp_path / "deleted", tmp_path))
    assert len(precs_deleted) == 1
    assert set(precs_deleted) == {precA}

    precs_deleted_shared = list(which_package(tmp_path / "deleted_shared", tmp_path))
    assert len(precs_deleted_shared) == 2
    assert set(precs_deleted_shared) == {precA, precB}

    # reuse environment, regression test for #5136
    (tmp_path / "conda-meta" / "packageA-1-0.json").unlink()
    (tmp_path / "conda-meta" / "packageB-1-0.json").unlink()

    # a dummy package with a hardlink file
    (tmp_path / "conda-meta" / "packageC-1-0.json").write_text(
        json.dumps(
            {
                "build": "0",
                "build_number": 0,
                "channel": "packageC-channel",
                "files": ["hardlinkA"],
                "name": "packageC",
                "paths_data": {
                    "paths": [
                        {
                            "_path": "hardlinkA",
                            "path_type": "hardlink",
                            "size_in_bytes": 0,
                        }
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
    precC = pd.get("packageC")

    # test returned package records given a path
    precs_reused = list(which_package(tmp_path / "hardlinkA", tmp_path))
    assert len(precs_reused) == 1
    assert set(precs_reused) == {precC}


@pytest.mark.benchmark
def test_which_package_battery(tmp_path: Path):
    # regression: https://github.com/conda/conda-build/issues/5126

    # NOTE: CodSpeed on Python 3.12+ activates the stack profiler trampoline backend
    # and thus runs the test twice (once without profiling and once with profiling),
    # unfortunately this means that on the second iteration tmp_path is no longer empty
    # so we create a randomized unique directory to compensate
    tmp_path = tmp_path / uuid4().hex
    tmp_path.mkdir()

    # create a dummy environment
    (tmp_path / "conda-meta").mkdir()
    (tmp_path / "conda-meta" / "history").touch()
    (tmp_path / "lib").mkdir()

    # dummy packages with files
    removed = []
    for _ in range(10):
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

    # removed files should still return a package
    # this occurs when, e.g., a build script removes files installed by another package
    # (post-install scripts removing files from the run environment is less
    # likely and not covered)
    for file in removed:
        assert len(list(which_package(tmp_path / file, tmp_path))) == 1

    # missing files should return no packages
    assert not len(list(which_package(tmp_path / "missing", tmp_path)))


def test_inspect_linkages_no_packages():
    with pytest.raises(CondaBuildUserError):
        inspect_linkages([])


@pytest.mark.skipif(not on_win, reason="inspect_linkages is available")
def test_inspect_linkages_on_win():
    with pytest.raises(CondaBuildUserError):
        inspect_linkages(["packages"])


@pytest.mark.skipif(on_win, reason="inspect_linkages is not available")
def test_inspect_linkages_not_installed():
    with pytest.raises(CondaBuildUserError):
        inspect_linkages(["not_installed_pkg"])


@pytest.mark.skipif(on_mac, reason="inspect_objects is only available on macOS")
def test_inspect_objects_not_on_mac():
    with pytest.raises(CondaBuildUserError):
        inspect_objects([])
