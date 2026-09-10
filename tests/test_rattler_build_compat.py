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

from conda_build import api
from conda_build._rattler_build.compat import is_v1_package
from conda_build.cli import main_build
from conda_build.config import Config
from conda_build.exceptions import CondaBuildUserError

if TYPE_CHECKING:
    from pathlib import Path


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
    def make(name, channel, *, dependencies=(), script="exit 0", include_recipe=True):
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
        create(str(source), list(files), str(package))
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
    create(str(source), list(files), str(package))

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
