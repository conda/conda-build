# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
import yaml
from conda.base.context import reset_context
from conda_index.api import update_index
from conda_package_handling.api import create
from conda_package_streaming.transmute import transmute

from conda_build import api
from conda_build._rattler_build.compat import (
    _load_variant_config,
    is_v1_package,
    run_rattler,
)
from conda_build.cli import main_build, main_render
from conda_build.config import Config
from conda_build.exceptions import CondaBuildUserError

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "filename", ("conda_build_config.yaml", "custom.yaml", "variants.yaml")
)
@pytest.mark.parametrize(
    "variant_yaml, expected",
    (
        pytest.param("value: 3.10\n", "3.10", id="scalar"),
        pytest.param(
            "value:\n  - 3.10  # [linux]\n  - 3.12  # [win]\n",
            "3.10",
            id="legacy-selectors",
        ),
        pytest.param(
            "value:\n  - 3.10  # [target_platform == 'linux-64' and host_platform]\n"
            "  - 3.12  # [target_platform in ['win-64', 'win-arm64']]\n",
            "3.10",
            id="legacy-platform-context",
        ),
        pytest.param(
            "value:\n  - 3.10  # [match('3.10', '>=3') and "
            "os.environ.get('CONDA_BUILD_TEST_SELECTOR').startswith('enabled')]\n",
            "3.10",
            id="legacy-functions",
        ),
        pytest.param(
            "value:\n  - if: linux\n    then: 3.10\n    else: 3.12\n",
            "3.10",
            id="native-conditional",
        ),
        pytest.param(
            "value: [\"${{ '3.10' if linux else '3.12' }}\"]\n",
            "3.10",
            id="native-template",
        ),
        pytest.param("value: [3.10]\n", "3.10", id="flow-list"),
        pytest.param(
            "# See [https://example.com/variants]\nvalue: [3.10]\n",
            "3.10",
            id="full-line-comment",
        ),
        pytest.param(
            "value: [3.10]  # See [https://example.com/variants]\n",
            "3.10",
            id="inline-comment",
        ),
        pytest.param(
            'value: ["literal # [win]"]\n', "literal # [win]", id="quoted-selector"
        ),
        pytest.param(
            'value: ["literal # [win]"]  # [linux]\n',
            "literal # [win]",
            id="quoted-text-before-selector",
        ),
        pytest.param(
            "value:\n  - |\n    literal # [win]\n",
            "literal # [win]\n",
            id="block-selector",
        ),
        pytest.param("value: [true]\n", True, id="boolean"),
    ),
)
def test_v1_variant_config_formats(
    tmp_path, capsys, monkeypatch, filename, variant_yaml, expected
):
    monkeypatch.setenv("CONDA_BUILD_TEST_SELECTOR", "enabled")
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    (recipe / "recipe.yaml").write_text(
        "package: {name: variant-config-test, version: '1'}\n"
        "build:\n  variant:\n    use_keys: [value]\n"
        "extra:\n  selected: ${{ value }}\n  is_boolean: ${{ value == true }}\n",
        encoding="utf-8",
    )
    variant_file = tmp_path / filename
    variant_file.write_text(variant_yaml, encoding="utf-8")
    _, args = main_render.parse_args([str(recipe)])
    config = Config(
        croot=str(tmp_path / "croot"),
        host_subdir="linux-64",
        ignore_system_variants=True,
        variant_config_files=[str(variant_file)],
    )

    assert run_rattler("render", args, config) == 0
    rendered = yaml.safe_load(capsys.readouterr().out)
    assert rendered["extra"]["selected"] == ("true" if expected is True else expected)
    assert rendered["extra"]["is_boolean"] == ("true" if expected is True else "false")


@pytest.mark.parametrize("option", ("-m", "--exclusive-config-file"))
def test_v1_render_legacy_variant_file(tmp_path, capsys, option):
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    (recipe / "recipe.yaml").write_text(
        "package: {name: legacy-variant-config-test, version: '${{ version }}'}\n"
        "build:\n  variant:\n    use_keys: [channel_targets]\n"
        "extra:\n  channel: ${{ channel_targets }}\n",
        encoding="utf-8",
    )
    variant_file = tmp_path / "conda_build_config_1.yaml"
    variant_file.write_text(
        "channel_targets: defaults\n"
        "version:\n  - 3.10  # [True]\n  - 3.12  # [False]\n",
        encoding="utf-8",
    )

    assert main_render.execute([str(recipe), option, str(variant_file)]) == 0
    rendered = yaml.safe_load(capsys.readouterr().out)
    assert rendered["package"]["version"] == "3.10"
    assert rendered["extra"]["channel"] == "defaults"


def test_v1_variant_config_zip_keys_and_filtered_values(tmp_path):
    variant_file = tmp_path / "custom.yaml"
    variant_file.write_text(
        "python: [3.10, 3.11]\n"
        "numpy: [1.24, 1.25]\n"
        "zip_keys: [[python, numpy]]\n"
        "pin_run_as_build: {python: {max_pin: x.x}}\n"
        "filtered:\n  - ignored  # [win]\n",
        encoding="utf-8",
    )

    variants = _load_variant_config(str(variant_file), Config(host_subdir="linux-64"))

    assert variants.combinations() == [
        {"python": "3.10", "numpy": "1.24"},
        {"python": "3.11", "numpy": "1.25"},
    ]


@contextmanager
def _configured_channel(channel):
    try:
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setenv("CONDA_CHANNELS", channel.as_uri())
            reset_context()
            yield
    finally:
        reset_context()


@pytest.fixture
def make_v1_test_package(tmp_path):
    def make(
        name, channel, *, dependencies=(), script="echo test", include_recipe=True
    ):
        source = tmp_path / name
        files = {
            "info/index.json": json.dumps(
                {
                    "name": name,
                    "version": "1",
                    "build": "0",
                    "build_number": 0,
                    "subdir": "noarch",
                    "noarch": "generic",
                    "depends": list(dependencies),
                }
            ),
            "info/files": "",
            "info/paths.json": json.dumps({"paths_version": 1, "paths": []}),
            "info/tests/tests.yaml": yaml.safe_dump([{"script": {"content": script}}]),
        }
        if include_recipe:
            files["info/recipe/recipe.yaml"] = yaml.safe_dump(
                {"package": {"name": name, "version": "1"}}
            )
        for filename, content in files.items():
            path = source / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        package = channel / "noarch" / f"{name}-1-0.conda"
        package.parent.mkdir(parents=True, exist_ok=True)
        tarball = package.with_suffix(".tar.bz2")
        create(str(source), list(files), str(tarball))
        transmute(str(tarball), str(package.parent))
        tarball.unlink()
        return package

    return make


@pytest.fixture
def v1_test_channels(tmp_path, make_v1_test_package):
    output = tmp_path / "output"
    make_v1_test_package("test-v1-upstream", output)
    downstream = make_v1_test_package(
        "test-v1-downstream", output, dependencies=("test-v1-upstream ==1",)
    )
    update_index(str(output))
    empty = tmp_path / "empty"
    (empty / "noarch").mkdir(parents=True)
    update_index(str(empty))
    cached = tmp_path / "external-cache" / downstream.name
    cached.parent.mkdir()
    shutil.copy2(downstream, cached)
    with _configured_channel(empty):
        yield output, empty, cached


def test_v1_cached_downstream_uses_output_folder(v1_test_channels, tmp_path):
    output, _, cached = v1_test_channels
    config = Config(croot=str(tmp_path / "croot"), output_folder=str(output))
    assert api.test(str(cached), config=config, move_broken=False) is True


def test_v1_package_uses_sibling_channel(v1_test_channels, tmp_path):
    output, _, cached = v1_test_channels
    package = output / "noarch" / cached.name
    assert (
        main_build.execute(["--test", str(package), "--croot", str(tmp_path / "croot")])
        == 0
    )


def test_v1_package_honors_configured_channel(v1_test_channels, tmp_path):
    output, _, cached = v1_test_channels
    with _configured_channel(output):
        assert (
            main_build.execute(
                ["--test", str(cached), "--croot", str(tmp_path / "croot")]
            )
            == 0
        )


@pytest.mark.parametrize("use_output_channel", (False, True))
def test_v1_package_override_channels(v1_test_channels, tmp_path, use_output_channel):
    output, empty, cached = v1_test_channels
    channel = output if use_output_channel else empty
    args = [
        "--test",
        str(cached),
        "--croot",
        str(tmp_path / "croot"),
        "--override-channels",
        "-c",
        channel.as_uri(),
    ]
    with _configured_channel(output):
        if use_output_channel:
            assert main_build.execute(args) == 0
        else:
            with pytest.raises(CondaBuildUserError):
                main_build.execute(args)


def test_v1_package_without_recipe_runs_tests(
    v1_test_channels, tmp_path, make_v1_test_package
):
    output, _, _ = v1_test_channels
    package = make_v1_test_package(
        "test-v1-failing", output, script="exit 1", include_recipe=False
    )
    assert is_v1_package(package)
    with pytest.raises(CondaBuildUserError):
        main_build.execute(["--test", str(package), "--croot", str(tmp_path / "croot")])


@pytest.mark.parametrize("extension", (".conda", ".tar.bz2"))
@pytest.mark.parametrize(
    "metadata_files, expected",
    (
        pytest.param(
            {
                "info/recipe/recipe.yaml": "package: {name: detector, version: '1'}\n",
                "info/recipe/rendered_recipe.yaml": "{}\n",
                "info/tests/tests.yaml": "- script: exit 1\n",
            },
            True,
            id="v1-included-recipe",
        ),
        pytest.param(
            {"info/tests/tests.yaml": "- script: exit 1\n"},
            True,
            id="v1-omitted-recipe",
        ),
        pytest.param(
            {"info/tests/tests.yaml": "[]\n"},
            True,
            id="v1-no-tests",
        ),
        pytest.param(
            {"info/recipe/recipe.yaml": "package: {name: detector, version: '1'}\n"},
            True,
            id="v1-recipe-marker",
        ),
        pytest.param(
            {"info/recipe/rendered_recipe.yaml": "{}\n"},
            True,
            id="v1-rendered-recipe-marker",
        ),
        pytest.param(
            {
                "info/recipe/meta.yaml": "package: {name: detector, version: '1'}\n",
                "info/test/run_test.sh": "exit 1\n",
            },
            False,
            id="v0-tests",
        ),
        pytest.param(
            {
                "info/recipe/meta.yaml": "package: {name: detector, version: '1'}\n",
                "share/info/tests/tests.yaml": "- script: exit 1\n",
            },
            False,
            id="v0-test-filename-outside-info",
        ),
    ),
)
def test_is_v1_package(tmp_path: Path, extension, metadata_files, expected):
    source = tmp_path / "source"
    files = {
        "info/index.json": json.dumps(
            {
                "name": "detector",
                "version": "1",
                "build": "0",
                "build_number": 0,
                "subdir": "noarch",
                "depends": [],
            }
        ),
        "share/detector-data": "data\n",
        **metadata_files,
    }
    for name, contents in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    package = tmp_path / f"detector-1-0{extension}"
    tarball = package.with_suffix(".tar.bz2") if extension == ".conda" else package
    create(str(source), list(files), str(tarball))
    if extension == ".conda":
        transmute(str(tarball), str(package.parent))
        tarball.unlink()

    assert is_v1_package(package) is expected


@pytest.mark.parametrize("input_kind", ("missing-package", "directory", "recipe-file"))
def test_is_v1_package_non_package(tmp_path: Path, input_kind):
    if input_kind == "missing-package":
        package = tmp_path / "missing-1-0.conda"
    elif input_kind == "directory":
        package = tmp_path
    else:
        package = tmp_path / "meta.yaml"
        package.write_text(
            "package: {name: detector, version: '1'}\n", encoding="utf-8"
        )

    assert is_v1_package(package) is False
