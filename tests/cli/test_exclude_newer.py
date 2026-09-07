# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import io
import json
import sys
import tarfile
from datetime import datetime, timezone

import pytest
import yaml
from conda.base.context import context, reset_context
from conda.core.index import Index
from conda.models.records import PackageRecord
from conda_index.api import update_index

from conda_build import environ
from conda_build.cli import main_build, main_render
from conda_build.config import Config
from conda_build.exceptions import CondaBuildUserError


@pytest.fixture(scope="session")
def warm_package_cache():
    return None


@pytest.fixture(autouse=True)
def isolated_context(monkeypatch, tmp_path):
    condarc = tmp_path / "condarc"
    condarc.write_text("channels: []\ncreate_default_packages: []\n")
    with monkeypatch.context() as patch:
        patch.setenv("CONDARC", str(condarc))
        patch.setenv("CONDA_SOLVER", "classic")
        patch.setenv("CONDA_PKGS_DIRS", str(tmp_path / "pkgs"))
        patch.delenv("CONDA_EXCLUDE_NEWER", raising=False)
        patch.delenv("CONDA_EXCLUDE_NEWER_PACKAGE", raising=False)
        reset_context()
        yield condarc
    reset_context()


@pytest.fixture
def policy_class():
    return pytest.importorskip("conda.core.exclude_newer").ExcludeNewerPolicy


def _timestamp(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


def _package(channel, subdir, name, version, timestamp, depends=()):
    folder = channel / subdir
    folder.mkdir(parents=True, exist_ok=True)
    payload = f"share/{name}/version.txt"
    metadata = {
        "name": name,
        "version": version,
        "build": "0",
        "build_number": 0,
        "subdir": subdir,
        "depends": list(depends),
        "timestamp": timestamp * 1000,
    }
    with tarfile.open(folder / f"{name}-{version}-0.tar.bz2", "w:bz2") as archive:
        for filename, content in {
            "info/index.json": json.dumps(metadata),
            "info/files": f"{payload}\n",
            payload: f"{version}\n",
        }.items():
            data = content.encode()
            info = tarfile.TarInfo(filename)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


@pytest.fixture
def local_channels(tmp_path, monkeypatch, policy_class):
    external = tmp_path / "external"
    output = tmp_path / "output"
    subdir = context.subdir
    _package(external, subdir, "cutoff-dependency", "1.0", _timestamp("2026-03-01"))
    _package(external, subdir, "cutoff-dependency", "2.0", _timestamp("2026-05-01"))
    _package(
        output,
        subdir,
        "cutoff-output",
        "1.0",
        _timestamp("2026-05-01"),
        depends=("cutoff-dependency",),
    )
    update_index(external)
    update_index(output)
    monkeypatch.setenv("CONDA_CHANNELS", external.as_uri())
    reset_context()
    return external, output


@pytest.mark.parametrize("command", [main_build, main_render], ids=["build", "render"])
@pytest.mark.parametrize(
    "value", ["7d", "2026-04-01", "2026-04-01T12:30:00Z", "1775001600"]
)
def test_cli_cutoff_forms(command, value, policy_class):
    _, parsed = command.parse_args(["recipe", "--exclude-newer", value])
    context.__init__(argparse_args=parsed)
    config = Config(**vars(parsed))
    expected = policy_class.from_values(value, {}, now=config._exclude_newer_now)
    assert config.exclude_newer_policy.global_cutoff == expected.global_cutoff


@pytest.mark.parametrize("command", [main_build, main_render], ids=["build", "render"])
@pytest.mark.parametrize(
    "env_value,cli_value,expected",
    [
        (None, None, "2026-01-01"),
        ("2026-02-01", None, "2026-02-01"),
        ("2026-02-01", "2026-03-01", "2026-03-01"),
    ],
)
def test_cli_cutoff_precedence(
    command, env_value, cli_value, expected, isolated_context, monkeypatch, policy_class
):
    isolated_context.write_text("channels: []\nexclude_newer: '2026-01-01'\n")
    if env_value:
        monkeypatch.setenv("CONDA_EXCLUDE_NEWER", env_value)
    reset_context()
    args = ["recipe"]
    if cli_value:
        args.extend(["--exclude-newer", cli_value])
    _, parsed = command.parse_args(args)
    context.__init__(argparse_args=parsed)
    config = Config(**vars(parsed))
    assert config.exclude_newer == expected
    assert config.exclude_newer_policy.active


def test_relative_cutoff_survives_config_copy(monkeypatch, policy_class):
    monkeypatch.setattr("conda_build.config.time.time", lambda: 2_000_000_000)
    config = Config(exclude_newer="7d")
    expected = config.exclude_newer_policy.global_cutoff
    monkeypatch.setattr("conda_build.config.time.time", lambda: 2_000_086_400)
    copied = config.copy()
    assert config.exclude_newer_policy.global_cutoff == expected
    assert copied.exclude_newer_policy.global_cutoff == expected
    assert Config(exclude_newer="7d").exclude_newer_policy.global_cutoff > expected


def test_explicit_cutoff_requires_new_conda(monkeypatch):
    monkeypatch.setitem(context.__dict__, "exclude_newer", None)
    monkeypatch.setitem(sys.modules, "conda.core.exclude_newer", None)
    with pytest.raises(CondaBuildUserError, match="requires conda 26.9 or newer"):
        Config(exclude_newer="7d").exclude_newer_policy
    assert Config().exclude_newer_policy is None


@pytest.mark.parametrize("command", [main_build, main_render], ids=["build", "render"])
@pytest.mark.parametrize("configured", [False, True], ids=["cli", "environment"])
@pytest.mark.parametrize("warm_cached_policy", [False, True], ids=["fresh", "cached"])
def test_v1_cutoff_is_rejected(
    command, configured, warm_cached_policy, tmp_path, monkeypatch, policy_class
):
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    (recipe / "recipe.yaml").write_text(
        "schema_version: 1\npackage:\n  name: cutoff-v1\n  version: '1.0'\n"
    )
    args = [str(recipe)]
    if warm_cached_policy:
        assert not context.exclude_newer_policy.active
    if configured:
        monkeypatch.setenv("CONDA_EXCLUDE_NEWER", "2026-04-01")
    else:
        args.extend(["--exclude-newer", "2026-04-01"])
    with pytest.raises(CondaBuildUserError, match="not supported for v1 recipes"):
        command.execute(args)


def test_injected_index_filters_external_channel_and_keeps_output(
    local_channels, tmp_path
):
    external, output = local_channels
    config = Config(output_folder=str(output), exclude_newer="2026-04-01")
    index = Index(
        channels=[output.as_uri(), external.as_uri()],
        prepend=False,
        platform=context.subdir,
    )
    previous_policy = context.exclude_newer_policy
    actions = environ._install_actions(
        str(tmp_path / "prefix"),
        index,
        ["cutoff-output"],
        subdir=context.subdir,
        exclude_newer_policy=config.exclude_newer_policy,
    )
    assert {record.name: record.version for record in actions["LINK"]} == {
        "cutoff-dependency": "1.0",
        "cutoff-output": "1.0",
    }
    assert context.exclude_newer_policy is previous_policy
    assert any(
        record.name == "cutoff-dependency" and record.version == "2.0"
        for record in index
    )


@pytest.mark.parametrize("env", ["build", "host", "test"])
def test_cached_unrestricted_solve_cannot_bypass_cutoff(local_channels, tmp_path, env):
    external, output = local_channels
    config = Config(output_folder=str(output), exclude_newer="2026-04-01")
    kwargs = {
        "prefix": str(tmp_path / env),
        "specs": ["cutoff-dependency"],
        "env": env,
        "subdir": context.subdir,
        "bldpkgs_dirs": (str(output / context.subdir),),
        "output_folder": str(output),
        "channel_urls": (external.as_uri(),),
    }
    unrestricted = environ.get_package_records(**kwargs)
    restricted = environ.get_package_records(
        **kwargs, exclude_newer_policy=config.exclude_newer_policy
    )
    unrestricted_again = environ.get_package_records(**kwargs)
    assert [record.version for record in unrestricted] == ["2.0"]
    assert [record.version for record in restricted] == ["1.0"]
    assert [record.version for record in unrestricted_again] == ["2.0"]


def test_template_with_newer_dependency_cannot_bypass_cutoff(local_channels, tmp_path):
    external, output = local_channels
    template = tmp_path / "template"
    target = tmp_path / "restricted"
    config = Config(
        croot=str(tmp_path),
        output_folder=str(output),
        channel_urls=[external.as_uri()],
    )
    specs = ["cutoff-dependency"]
    environ.create_env(str(template), specs, "test", config, context.subdir)
    payload = "share/cutoff-dependency/version.txt"
    assert (template / payload).read_text().strip() == "2.0"
    assert environ._clone_template_env(template, tmp_path / "clone", specs)

    config.exclude_newer = "2026-04-01"
    config.test_env_template = str(template)
    environ.create_env(str(target), specs, "test", config, context.subdir)
    assert (target / payload).read_text().strip() == "1.0"
    assert (template / payload).read_text().strip() == "2.0"


def test_output_exemption_does_not_include_other_file_channels(local_channels):
    external, output = local_channels
    policy = Config(
        output_folder=str(output), exclude_newer="2026-04-01"
    ).exclude_newer_policy
    fields = {
        "name": "cutoff-output",
        "version": "1.0",
        "build": "0",
        "build_number": 0,
        "subdir": context.subdir,
        "timestamp": _timestamp("2026-05-01") * 1000,
    }
    assert policy.should_include(PackageRecord(channel=output.as_uri(), **fields))
    assert not policy.should_include(PackageRecord(channel=external.as_uri(), **fields))


def test_build_uses_cutoff_in_build_host_and_test_environments(
    local_channels, tmp_path
):
    external, output = local_channels
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    if sys.platform == "win32":
        check_prefix = (
            'findstr /x "1.0" "%PREFIX%\\share\\cutoff-dependency\\version.txt"'
        )
        check_build_prefix = (
            'findstr /x "1.0" "%BUILD_PREFIX%\\share\\cutoff-dependency\\version.txt"'
        )
    else:
        check_prefix = (
            'test "$(cat "$PREFIX/share/cutoff-dependency/version.txt")" = "1.0"'
        )
        check_build_prefix = (
            'test "$(cat "$BUILD_PREFIX/share/cutoff-dependency/version.txt")" = "1.0"'
        )
    (recipe / "meta.yaml").write_text(
        yaml.safe_dump(
            {
                "package": {"name": "cutoff-build", "version": "1.0"},
                "build": {"number": 0, "script": [check_prefix, check_build_prefix]},
                "requirements": {
                    "build": ["cutoff-dependency"],
                    "host": ["cutoff-dependency"],
                    "run": ["cutoff-dependency"],
                },
                "test": {"commands": [check_prefix]},
            }
        )
    )
    assert (
        main_build.execute(
            [
                str(recipe),
                "--exclude-newer=2026-04-01",
                "--override-channels",
                f"--channel={external.as_uri()}",
                f"--output-folder={output}",
                "--no-anaconda-upload",
                "--no-activate",
            ]
        )
        == 0
    )
    assert list((output / context.subdir).glob("cutoff-build-1.0-*.conda"))
