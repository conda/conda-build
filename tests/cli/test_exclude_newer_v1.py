# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import inspect
import io
import json
import sys
import tarfile

import pytest
import yaml
from conda.base.context import context, reset_context
from conda_index.api import update_index
from rattler_build.debug import DebugSession
from rattler_build.package import Package
from rattler_build.stage0 import RenderedVariant

from conda_build.cli import main_build, main_debug
from conda_build.config import Config
from conda_build.exceptions import CondaBuildUserError

from .test_exclude_newer import (
    _package,
    _timestamp,
)
from .test_exclude_newer import (
    isolated_context as isolated_context,
)
from .test_exclude_newer import (
    policy_class as policy_class,
)
from .test_exclude_newer import (
    warm_package_cache as warm_package_cache,
)


@pytest.fixture
def v1_policy_support():
    for method in (RenderedVariant.run_build, Package.run_tests, DebugSession.create):
        if "exclude_newer_channel" not in inspect.signature(method).parameters:
            pytest.skip(
                "py-rattler-build does not yet support scoped dependency cutoffs"
            )


@pytest.fixture
def v1_channels(tmp_path, monkeypatch, policy_class):
    external = tmp_path / "external"
    output = tmp_path / "output"
    for environment in ("build", "host", "test"):
        for version, release in (("1.0", "2026-03-01"), ("2.0", "2026-05-01")):
            _package(
                external,
                context.subdir,
                f"cutoff-{environment}-dependency",
                version,
                _timestamp(release),
            )
    update_index(external)
    monkeypatch.setenv("CONDA_CHANNELS", external.as_uri())
    reset_context()
    return external, output


def _check_version(prefix, package, version):
    if sys.platform == "win32":
        return f'findstr /x "{version}" "%{prefix}%\\share\\{package}\\version.txt"'
    return f'test "$(cat "${prefix}/share/{package}/version.txt")" = "{version}"'


def _write_payload(package, version):
    if sys.platform == "win32":
        return [
            f'mkdir "%PREFIX%\\share\\{package}"',
            f'echo {version}> "%PREFIX%\\share\\{package}\\version.txt"',
        ]
    return [
        f'mkdir -p "$PREFIX/share/{package}"',
        f'echo "{version}" > "$PREFIX/share/{package}/version.txt"',
    ]


@pytest.fixture
def v1_recipe(tmp_path):
    def write_recipe(*, build="1.0", host="1.0", test="1.0", sibling=False):
        recipe_dir = tmp_path / "recipe"
        recipe_dir.mkdir(exist_ok=True)
        name = "cutoff-v1"
        output = {
            "package": {"name": name, "version": "1.0"},
            "build": {
                "script": [
                    _check_version("BUILD_PREFIX", "cutoff-build-dependency", build),
                    _check_version("PREFIX", "cutoff-host-dependency", host),
                    *_write_payload(name, "1.0"),
                ],
            },
            "requirements": {
                "build": ["cutoff-build-dependency"],
                "host": ["cutoff-host-dependency"],
            },
            "tests": [
                {
                    "script": [
                        _check_version("PREFIX", name, "1.0"),
                        _check_version("PREFIX", "cutoff-test-dependency", test),
                    ],
                    "requirements": {"run": ["cutoff-test-dependency"]},
                },
            ],
        }
        if sibling:
            sibling_name = "cutoff-v1-sibling"
            output["requirements"]["host"].append(sibling_name)
            output["requirements"]["run"] = [sibling_name]
            check = _check_version("PREFIX", sibling_name, "1.0")
            output["build"]["script"].insert(0, check)
            output["tests"][0]["script"].append(check)
            recipe = {
                "schema_version": 1,
                "outputs": [
                    {
                        "package": {"name": sibling_name, "version": "1.0"},
                        "build": {"script": _write_payload(sibling_name, "1.0")},
                    },
                    output,
                ],
            }
        else:
            recipe = {"schema_version": 1, **output}
        (recipe_dir / "recipe.yaml").write_text(yaml.safe_dump(recipe, sort_keys=False))
        return recipe_dir

    return write_recipe


def _build_args(recipe, external, output, *, channel=None):
    return [
        str(recipe),
        "--override-channels",
        f"--channel={channel or external.as_uri()}",
        f"--output-folder={output}",
        "--no-anaconda-upload",
    ]


def test_v1_build_without_cutoff(v1_channels, v1_recipe):
    external, output = v1_channels
    recipe = v1_recipe(build="2.0", host="2.0", test="2.0", sibling=True)
    assert main_build.execute(_build_args(recipe, external, output)) == 0


@pytest.mark.parametrize(
    "sibling", [False, True], ids=["single-output", "sibling-output"]
)
def test_v1_build_uses_cutoff_in_build_host_and_test_environments(
    v1_policy_support, v1_channels, v1_recipe, sibling
):
    external, output = v1_channels
    recipe = v1_recipe(sibling=sibling)
    assert (
        main_build.execute(
            [*_build_args(recipe, external, output), "--exclude-newer=2026-04-01"]
        )
        == 0
    )
    assert len(list((output / context.subdir).glob("cutoff-v1-1.0-*.conda"))) == 1
    if sibling:
        assert (
            len(list((output / context.subdir).glob("cutoff-v1-sibling-1.0-*.conda")))
            == 1
        )


@pytest.mark.parametrize(
    "env_value,cli_value,expected",
    [
        (None, None, "2.0"),
        ("2026-04-01", None, "1.0"),
        ("2026-04-01", "2026-06-01", "2.0"),
    ],
    ids=["condarc", "environment-over-condarc", "cli-over-environment"],
)
def test_v1_cutoff_precedence_selects_dependencies(
    v1_policy_support,
    v1_channels,
    v1_recipe,
    isolated_context,
    monkeypatch,
    env_value,
    cli_value,
    expected,
):
    isolated_context.write_text("channels: []\nexclude_newer: '2026-06-01'\n")
    if env_value:
        monkeypatch.setenv("CONDA_EXCLUDE_NEWER", env_value)
    reset_context()
    external, output = v1_channels
    recipe = v1_recipe(build=expected, host=expected, test=expected)
    args = _build_args(recipe, external, output)
    if cli_value:
        args.append(f"--exclude-newer={cli_value}")
    assert main_build.execute(args) == 0


@pytest.mark.parametrize(
    "global_cutoff,overrides,expected",
    [
        ("2026-04-01", {"cutoff-build-dependency": False}, ("2.0", "1.0", "1.0")),
        ("2026-06-01", {"cutoff-host-dependency": "2026-04-01"}, ("2.0", "1.0", "2.0")),
        (None, {"cutoff-test-dependency": "2026-04-01"}, ("2.0", "2.0", "1.0")),
    ],
    ids=["exempt-build-package", "stricter-host-package", "test-package-only"],
)
def test_v1_package_cutoff_overrides(
    v1_policy_support,
    v1_channels,
    v1_recipe,
    isolated_context,
    global_cutoff,
    overrides,
    expected,
):
    settings = {"channels": [], "exclude_newer_package": overrides}
    if global_cutoff is not None:
        settings["exclude_newer"] = global_cutoff
    isolated_context.write_text(yaml.safe_dump(settings))
    reset_context()
    external, output = v1_channels
    build, host, test = expected
    recipe = v1_recipe(build=build, host=host, test=test, sibling=True)
    assert main_build.execute(_build_args(recipe, external, output)) == 0


@pytest.mark.parametrize(
    "global_cutoff,channel_cutoff,expected",
    [
        ("2026-04-01", False, "2.0"),
        ("2026-06-01", "2026-04-01", "1.0"),
        (None, "2026-04-01", "1.0"),
    ],
    ids=["exempt-channel", "stricter-channel", "channel-only"],
)
def test_v1_file_channel_cutoff_overrides(
    v1_policy_support,
    v1_channels,
    v1_recipe,
    isolated_context,
    global_cutoff,
    channel_cutoff,
    expected,
):
    external, output = v1_channels
    settings = {
        "channels": [],
        "channel_settings": [
            {"channel": external.as_uri(), "exclude_newer": channel_cutoff}
        ],
    }
    if global_cutoff is not None:
        settings["exclude_newer"] = global_cutoff
    isolated_context.write_text(yaml.safe_dump(settings))
    reset_context()
    recipe = v1_recipe(build=expected, host=expected, test=expected, sibling=True)
    assert main_build.execute(_build_args(recipe, external, output)) == 0


@pytest.mark.parametrize("selector", ["alias", "custom-channel", "url-glob"])
def test_v1_cutoff_matches_configured_channels(
    v1_policy_support, v1_channels, v1_recipe, isolated_context, tmp_path, selector
):
    external, output = v1_channels
    settings = {"channels": [], "exclude_newer": "2026-06-01"}
    if selector == "alias":
        settings["channel_alias"] = tmp_path.as_uri()
        channel = "external"
        pattern = channel
    elif selector == "custom-channel":
        settings["channel_alias"] = (tmp_path / "unused").as_uri()
        settings["custom_channels"] = {"external": tmp_path.as_uri()}
        channel = "external"
        pattern = channel
    else:
        channel = external.as_uri()
        pattern = f"{tmp_path.as_uri()}/exter*"
    settings["channel_settings"] = [{"channel": pattern, "exclude_newer": "2026-04-01"}]
    isolated_context.write_text(yaml.safe_dump(settings))
    reset_context()
    assert (
        main_build.execute(_build_args(v1_recipe(), external, output, channel=channel))
        == 0
    )


def test_v1_cutoff_keeps_dependencies_without_timestamps(
    v1_policy_support, v1_channels, v1_recipe
):
    external, output = v1_channels
    for environment in ("build", "host", "test"):
        archive_path = (
            external / context.subdir / f"cutoff-{environment}-dependency-2.0-0.tar.bz2"
        )
        with tarfile.open(archive_path) as archive:
            contents = [
                (member, archive.extractfile(member).read()) for member in archive
            ]
        with tarfile.open(archive_path, "w:bz2") as archive:
            for member, content in contents:
                if member.name == "info/index.json":
                    metadata = json.loads(content)
                    del metadata["timestamp"]
                    content = json.dumps(metadata).encode()
                    member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
    update_index(external)
    repodata = json.loads((external / context.subdir / "repodata.json").read_text())
    assert all(
        "timestamp" not in record
        for record in repodata["packages"].values()
        if record["version"] == "2.0"
    )
    recipe = v1_recipe(build="2.0", host="2.0", test="2.0")
    assert (
        main_build.execute(
            [*_build_args(recipe, external, output), "--exclude-newer=2026-04-01"]
        )
        == 0
    )


def test_v1_debug_installs_dependencies_before_cutoff(
    v1_policy_support, v1_channels, v1_recipe, tmp_path
):
    external, _ = v1_channels
    recipe = v1_recipe()
    assert (
        main_debug.execute(
            [
                str(recipe),
                "--exclude-newer=2026-04-01",
                "--override-channels",
                f"--channel={external.as_uri()}",
            ]
        )
        == 0
    )
    for environment in ("build", "host"):
        payloads = list(
            tmp_path.glob(
                f"debug_*/**/share/cutoff-{environment}-dependency/version.txt"
            )
        )
        assert len(payloads) == 1
        assert payloads[0].read_text().strip() == "1.0"


@pytest.mark.parametrize(
    "channel",
    [
        "https://example.invalid/t/synthetic-token/packages",
        "https://synthetic-user:synthetic-password@example.invalid/packages",
    ],
)
def test_v1_channel_cutoff_preserves_credentials(
    channel, isolated_context, policy_class
):
    from conda_build._rattler_build.compat import exclude_newer_arguments

    isolated_context.write_text(
        yaml.safe_dump(
            {
                "channels": [],
                "exclude_newer": "2026-06-01",
                "channel_settings": [
                    {
                        "channel": "https://example.invalid/packages",
                        "exclude_newer": False,
                    }
                ],
            }
        )
    )
    reset_context()
    arguments = exclude_newer_arguments(Config(), [channel])
    assert arguments["exclude_newer_channel"] == {channel + "/": None}


def test_v1_cutoff_requires_supported_python_bindings(
    v1_recipe, monkeypatch, policy_class
):
    def old_run_build(self, exclude_newer=None, exclude_newer_package=None):
        pytest.fail("an unsupported binding must fail before creating environments")

    monkeypatch.setattr(RenderedVariant, "run_build", old_run_build)
    recipe = v1_recipe()
    with pytest.raises(CondaBuildUserError, match="py-rattler-build"):
        main_build.execute([str(recipe), "--exclude-newer=2026-04-01"])
