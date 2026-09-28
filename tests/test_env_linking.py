# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import json
import os
import subprocess

import pytest
from conda.base.context import context, reset_context
from conda.models.records import PackageRecord
from conda_package_handling.api import create

from conda_build import environ


@pytest.fixture(scope="session")
def warm_package_cache():
    # These tests install only the local package below.
    return None


@pytest.fixture
def env_package(tmp_path, monkeypatch, mocker, testing_config):
    metadata = {
        "name": "link-probe",
        "version": "1",
        "build": "0",
        "build_number": 0,
        "subdir": "noarch",
        "noarch": "generic",
        "depends": [],
    }
    source = tmp_path / "package"
    files = {
        "info/index.json": json.dumps(metadata),
        "info/files": "share/value\n",
        "share/value": "unchanged package contents\n",
    }
    for filename, contents in files.items():
        path = source / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    archive = tmp_path / "link-probe-1-0.tar.bz2"
    create(str(source), list(files), str(archive))
    record = PackageRecord(
        **metadata, fn=archive.name, url=archive.as_uri(), channel=tmp_path.as_uri()
    )
    cache = tmp_path / "pkgs"
    condarc = tmp_path / "condarc"
    condarc.write_text("channels: []\ncreate_default_packages: []\n")
    testing_config.test_env_template = None
    testing_config.max_env_retry = 0
    mocker.patch.object(environ, "get_build_index", return_value=({}, None, None))
    try:
        with monkeypatch.context() as patch:
            patch.setenv("CONDARC", str(condarc))
            patch.setenv("CONDA_PKGS_DIRS", str(cache))
            patch.setenv("CONDA_OFFLINE", "true")
            patch.setenv("CONDA_ALWAYS_COPY", "false")
            patch.setenv("CONDA_ALWAYS_SOFTLINK", "false")
            reset_context()
            yield record, cache / "link-probe-1-0" / "share" / "value"
    finally:
        reset_context()


@pytest.mark.parametrize("on_mac", [False, True])
@pytest.mark.parametrize("env", ["build", "host"])
@pytest.mark.parametrize("retry", [False, True])
def test_create_env_link_type(
    tmp_path, mocker, testing_config, env_package, on_mac, env, retry
):
    record, cached = env_package
    mocker.patch.object(environ, "on_mac", on_mac)
    if retry:
        testing_config.max_env_retry = 1
        mocker.patch.object(
            environ,
            "_execute_actions",
            wraps=environ._execute_actions,
            side_effect=[OSError("transient install error"), mocker.DEFAULT],
        )
    prefix = tmp_path / "prefix"

    environ.create_env(
        str(prefix), [record], env=env, config=testing_config, subdir="noarch"
    )

    installed = prefix / "share" / "value"
    assert installed.read_bytes() == cached.read_bytes()
    assert installed.samefile(cached) is not on_mac
    assert not context.always_copy
    assert not context.always_softlink
    assert os.environ["CONDA_ALWAYS_COPY"] == "false"


@pytest.mark.parametrize("clone_succeeds", [False, True])
def test_create_env_template_uses_copies(
    tmp_path, mocker, testing_config, env_package, clone_succeeds
):
    record, cached = env_package
    mocker.patch.object(environ, "on_mac", False)
    template = tmp_path / "template"
    environ.create_env(
        str(template), [record], env="host", config=testing_config, subdir="noarch"
    )
    assert (template / "share" / "value").samefile(cached)

    mocker.patch.object(environ, "on_mac", True)
    testing_config.test_env_template = str(template)
    clone = mocker.spy(environ, "_clone_template_env")
    if not clone_succeeds:
        mocker.patch.object(
            environ.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)
        )
    prefix = tmp_path / "prefix"
    environ.create_env(
        str(prefix), [record], env="host", config=testing_config, subdir="noarch"
    )

    installed = prefix / "share" / "value"
    assert installed.read_bytes() == cached.read_bytes()
    assert not installed.samefile(cached)
    assert clone.spy_return is clone_succeeds
    assert not context.always_copy
    assert not context.always_softlink


@pytest.mark.parametrize("copy_value,softlink_value", [(None, None), ("false", "true")])
@pytest.mark.parametrize("fail", [False, True])
def test_create_env_restores_link_settings(
    tmp_path,
    monkeypatch,
    mocker,
    testing_config,
    env_package,
    copy_value,
    softlink_value,
    fail,
):
    record, cached = env_package
    for name, value in (
        ("CONDA_ALWAYS_COPY", copy_value),
        ("CONDA_ALWAYS_SOFTLINK", softlink_value),
    ):
        if value is None:
            monkeypatch.delenv(name)
        else:
            monkeypatch.setenv(name, value)
    condarc = tmp_path / "custom-condarc.yaml"
    condarc.write_text("remote_connect_timeout_secs: 19\n")
    reset_context(search_path=(str(condarc),), argparse_args={"remote_max_retries": 7})
    assert context.remote_connect_timeout_secs == 19
    mocker.patch.object(environ, "on_mac", True)
    if fail:
        mocker.patch.object(
            environ, "_execute_actions", side_effect=ValueError("install failed")
        )
    prefix = tmp_path / "prefix"

    if fail:
        with pytest.raises(ValueError, match="install failed"):
            environ.create_env(
                str(prefix),
                [record],
                env="host",
                config=testing_config,
                subdir="noarch",
            )
    else:
        environ.create_env(
            str(prefix), [record], env="host", config=testing_config, subdir="noarch"
        )
        installed = prefix / "share" / "value"
        assert not installed.is_symlink()
        assert not installed.samefile(cached)

    assert os.environ.get("CONDA_ALWAYS_COPY") == copy_value
    assert os.environ.get("CONDA_ALWAYS_SOFTLINK") == softlink_value
    assert context.always_copy is False
    assert context.always_softlink is (softlink_value == "true")
    assert context.remote_max_retries == 7
    assert context.remote_connect_timeout_secs == 19


def test_create_env_respects_final_link_settings(
    tmp_path, monkeypatch, mocker, testing_config, env_package
):
    record, cached = env_package
    condarc = tmp_path / "condarc.yaml"
    condarc.write_text("always_copy: false #!final\nalways_softlink: false #!final\n")
    monkeypatch.setenv("CONDARC", str(condarc))
    reset_context()
    mocker.patch.object(environ, "on_mac", True)
    prefix = tmp_path / "prefix"

    environ.create_env(
        str(prefix), [record], env="host", config=testing_config, subdir="noarch"
    )

    assert (prefix / "share" / "value").samefile(cached)
