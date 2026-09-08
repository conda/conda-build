# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from conda.models.records import PrefixRecord

from conda_build import _link, convert, noarch_python, utils, windows
from conda_build.exceptions import CondaBuildUserError


@pytest.fixture
def launcher_package(tmp_path, mocker):
    prefix = tmp_path / "launchers"
    paths = []
    for arch in ("32", "64", "arm64"):
        for kind in ("cli", "gui"):
            short_path = f"share/conda-launchers/{kind}-{arch}.exe"
            path = prefix / short_path
            path.parent.mkdir(parents=True, exist_ok=True)
            content = f"{kind}-{arch}".encode()
            path.write_bytes(content)
            paths.append(
                {
                    "_path": short_path,
                    "path_type": "hardlink",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_in_bytes": len(content),
                }
            )
    record = PrefixRecord(
        name="conda-launchers",
        version="24.7.1",
        build="0",
        build_number=0,
        subdir="noarch",
        files=[path["_path"] for path in paths],
        paths_data={"paths_version": 1, "paths": paths},
    )
    metadata = prefix / "conda-meta" / "conda-launchers-24.7.1-0.json"
    metadata.parent.mkdir()
    metadata.write_text(json.dumps(record.dump()))
    mocker.patch.object(utils.sys, "prefix", str(prefix))
    return prefix


@pytest.mark.parametrize("arch", ["32", "64", "arm64"])
@pytest.mark.parametrize("kind", ["cli", "gui"])
def test_locate_conda_launcher(launcher_package, arch, kind):
    path = utils.locate_conda_launcher(arch, launcher_type=kind)
    assert Path(path).read_bytes() == f"{kind}-{arch}".encode()


@pytest.mark.parametrize("problem", ["unowned", "missing", "modified", "no-hash"])
def test_locate_conda_launcher_rejects_invalid_source(launcher_package, problem):
    path = launcher_package / "share/conda-launchers/cli-arm64.exe"
    metadata = launcher_package / "conda-meta/conda-launchers-24.7.1-0.json"
    record = json.loads(metadata.read_text())
    if problem == "unowned":
        record["paths_data"]["paths"] = [
            item
            for item in record["paths_data"]["paths"]
            if item["_path"] != path.relative_to(launcher_package).as_posix()
        ]
    elif problem == "missing":
        path.unlink()
    elif problem == "modified":
        path.write_bytes(b"modified")
    else:
        for item in record["paths_data"]["paths"]:
            item.pop("sha256", None)
    metadata.write_text(json.dumps(record))

    with pytest.raises(
        FileNotFoundError if problem == "unowned" else CondaBuildUserError
    ):
        utils.locate_conda_launcher("arm64")


def test_locate_conda_launcher_requires_package_record(launcher_package):
    (launcher_package / "conda-meta/conda-launchers-24.7.1-0.json").unlink()
    with pytest.raises(CondaBuildUserError, match="Install conda-launchers"):
        utils.locate_conda_launcher("64")


def test_locate_conda_launcher_rechecks_source(launcher_package):
    path = utils.locate_conda_launcher("arm64")
    Path(path).write_bytes(b"changed after initial use")
    with pytest.raises(CondaBuildUserError, match="SHA256 mismatch"):
        utils.locate_conda_launcher("arm64")


def test_locate_conda_launcher_does_not_fall_back_to_x64(launcher_package):
    metadata = launcher_package / "conda-meta/conda-launchers-24.7.1-0.json"
    record = json.loads(metadata.read_text())
    record["paths_data"]["paths"] = [
        item for item in record["paths_data"]["paths"] if "-32.exe" not in item["_path"]
    ]
    metadata.write_text(json.dumps(record))

    with pytest.raises(FileNotFoundError, match="cli-32.exe"):
        utils.locate_conda_launcher("32")

    assert Path(utils.locate_conda_launcher("64")).read_bytes() == b"cli-64"


@pytest.mark.parametrize("arch", ["32", "64", "arm64"])
def test_create_entry_point(launcher_package, mocker, tmp_path, testing_config, arch):
    mocker.patch.object(utils, "on_win", True)
    testing_config.arch = arch
    path = tmp_path / "example"
    utils.create_entry_point(
        str(path), "conda_build.cli.main_build", "execute", testing_config
    )
    assert path.with_name("example-script.py").is_file()
    assert path.with_suffix(".exe").read_bytes() == f"cli-{arch}".encode()


@pytest.mark.parametrize("arch", ["32", "64", "arm64"])
def test_convert_uses_target_launcher(launcher_package, tmp_path, arch):
    convert.create_exe_file(str(tmp_path), "example", f"win-{arch}")
    assert (tmp_path / "example.exe").read_bytes() == f"cli-{arch}".encode()


@pytest.mark.parametrize("arch", ["32", "64", "arm64"])
def test_windows_scripts_use_target_launcher(
    launcher_package, tmp_path, testing_config, arch
):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "example").write_bytes(b"#!python\nprint('hello')\n")
    testing_config.arch = arch
    windows.fix_staged_scripts(str(scripts), testing_config)
    assert (scripts / "example.exe").read_bytes() == f"cli-{arch}".encode()


def test_legacy_link_selects_arm64_launcher(tmp_path, mocker):
    scripts = tmp_path / "python-scripts"
    scripts.mkdir()
    (scripts / "example").write_text("print('hello')\n")
    (tmp_path / "cli-arm64.exe").write_bytes(b"arm64")
    (tmp_path / "cli-64.exe").write_bytes(b"x64")
    target = tmp_path / "Scripts"
    target.mkdir()
    mocker.patch.object(_link, "THIS_DIR", str(tmp_path))
    mocker.patch.object(_link, "BIN_DIR", str(target))
    mocker.patch.object(_link, "FILES", [])
    mocker.patch.object(_link.sys, "platform", "win32")
    mocker.patch.object(_link.sysconfig, "get_platform", return_value="win-arm64")

    _link.create_script("example")

    assert (target / "example.exe").read_bytes() == b"arm64"


@pytest.mark.parametrize("missing_win32", [False, True])
def test_legacy_noarch_packages_available_launchers(
    launcher_package, tmp_path, testing_metadata, mocker, missing_win32
):
    if missing_win32:
        metadata = launcher_package / "conda-meta/conda-launchers-24.7.1-0.json"
        record = json.loads(metadata.read_text())
        record["paths_data"]["paths"] = [
            item
            for item in record["paths_data"]["paths"]
            if "-32.exe" not in item["_path"]
        ]
        metadata.write_text(json.dumps(record))
    mocker.patch.object(noarch_python, "on_win", False)
    mocker.patch.object(noarch_python, "bin_dirname", "bin")
    script = tmp_path / "bin" / "example"
    script.parent.mkdir()
    script.write_text("print('hello')\n")

    noarch_python.transform(testing_metadata, ["bin/example"], str(tmp_path))

    for arch in ("64", "arm64"):
        assert (tmp_path / f"cli-{arch}.exe").read_bytes() == f"cli-{arch}".encode()
    assert (tmp_path / "cli-32.exe").exists() is not missing_win32


def test_legacy_noarch_rejects_modified_launcher(
    launcher_package, tmp_path, testing_metadata, mocker
):
    (launcher_package / "share/conda-launchers/cli-arm64.exe").write_bytes(b"modified")
    mocker.patch.object(noarch_python, "on_win", False)
    mocker.patch.object(noarch_python, "bin_dirname", "bin")
    script = tmp_path / "bin" / "example"
    script.parent.mkdir()
    script.write_text("print('hello')\n")

    with pytest.raises(CondaBuildUserError, match="SHA256 mismatch"):
        noarch_python.transform(testing_metadata, ["bin/example"], str(tmp_path))
