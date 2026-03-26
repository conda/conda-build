# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
import yaml
from conda.exceptions import PackagesNotFoundError

from conda_build import api
from conda_build.cli import main_render

from .. import LOCAL_CHANNEL_PATH, METADATA_V2_PATH
from ..utils import metadata_dir

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture

    from conda_build.metadata import MetaData


def test_render_add_channel(
    tmp_path: Path,
    mock_channels: list[str],  # mock context.channels so its empty
) -> None:
    """This recipe requires the local-channel::small-executable package.
    This verifies that the --channel argument works."""
    rendered_filename = tmp_path / "out.yaml"
    main_render.execute(
        [
            f"--channel={LOCAL_CHANNEL_PATH}",
            str(METADATA_V2_PATH / "recipe_requiring_external_channel"),
            f"--file={rendered_filename}",
        ]
    )

    rendered_meta = yaml.safe_load(rendered_filename.read_text())
    reqs = rendered_meta["requirements"]["build"]
    assert len(reqs) == 1
    assert reqs[0] == "small-executable 1.0.0 0"


def test_render_with_empty_channel_fails(
    tmp_path: Path,
    mock_channels: list[str],  # mock context.channels so its empty
) -> None:
    with pytest.raises(PackagesNotFoundError):
        main_render.execute(
            [
                str(METADATA_V2_PATH / "recipe_requiring_external_channel"),
                f"--file={tmp_path / 'out.yaml'}",
            ]
        )


def test_render_output_build_path(
    testing_workdir, testing_config, testing_metadata, capfd, caplog
):
    api.output_yaml(testing_metadata, "meta.yaml")
    args = ["--output", testing_workdir]
    main_render.execute(args)
    test_path = os.path.join(
        testing_config.croot,
        testing_metadata.config.host_subdir,
        "test_render_output_build_path-1.0-1.conda",
    )
    output, error = capfd.readouterr()
    assert output.rstrip() == test_path, error
    assert error == ""


def test_render_output_build_path_and_file(
    testing_workdir, testing_config, testing_metadata, capfd, caplog
):
    api.output_yaml(testing_metadata, "meta.yaml")
    rendered_filename = "out.yaml"
    args = ["--output", "--file", rendered_filename, testing_workdir]
    main_render.execute(args)
    test_path = os.path.join(
        testing_config.croot,
        testing_metadata.config.host_subdir,
        "test_render_output_build_path_and_file-1.0-1.conda",
    )
    output, error = capfd.readouterr()
    assert output.rstrip() == test_path, error
    assert error == ""
    with open(rendered_filename) as rendered_file:
        rendered_meta = yaml.safe_load(rendered_file)
    assert rendered_meta["package"]["name"] == "test_render_output_build_path_and_file"


@pytest.mark.parametrize("version", ["2.7", "3.12"])
def test_render_output_build_path_set_python(
    testing_workdir: str,
    testing_metadata: MetaData,
    capfd: CaptureFixture,
    version: str,
):
    testing_metadata.meta["requirements"] = {"host": ["python"], "run": ["python"]}
    api.output_yaml(testing_metadata, "meta.yaml")

    api.output_yaml(testing_metadata, "meta.yaml")
    metadata = api.render(testing_workdir, python=version)[0][0]

    args = ["--output", testing_workdir, "--python", version]
    main_render.execute(args)

    major, minor = version.split(".")
    hash_ = metadata.hash_dependencies()
    test_path = (
        f"test_render_output_build_path_set_python-1.0-py{major}{minor}{hash_}_1.conda"
    )
    output, error = capfd.readouterr()
    assert os.path.basename(output.strip()) == test_path, error


@pytest.mark.slow
def test_render_with_python_arg_reduces_subspace(capfd):
    recipe = os.path.join(metadata_dir, "..", "variants", "20_subspace_selection_cli")
    # build the package
    args = [recipe, "--python=2.7", "--output"]
    main_render.execute(args)
    out, err = capfd.readouterr()
    assert len(out.splitlines()) == 2

    args = [recipe, "--python=3.9", "--output"]
    main_render.execute(args)
    out, err = capfd.readouterr()
    assert len(out.splitlines()) == 1

    # should raise an error, because python 3.6 is not in the matrix, so we don't know which vc
    # to associate with
    args = [recipe, "--python=3.6", "--output"]
    with pytest.raises(ValueError):
        main_render.execute(args)


def test_render_with_python_arg_CLI_reduces_subspace(capfd):
    recipe = os.path.join(metadata_dir, "..", "variants", "20_subspace_selection_cli")
    # build the package
    args = [recipe, "--variants", "{python: [2.7, 3.9]}", "--output"]
    main_render.execute(args)
    out, err = capfd.readouterr()
    assert len(out.splitlines()) == 3

    args = [recipe, "--variants", "{python: 2.7}", "--output"]
    main_render.execute(args)
    out, err = capfd.readouterr()
    assert len(out.splitlines()) == 2

    args = [recipe, "--variants", "{python: 3.9}", "--output"]
    main_render.execute(args)
    out, err = capfd.readouterr()
    assert len(out.splitlines()) == 1


def test_render_with_v1_recipe() -> None:
    """Test rendering a v1 recipe (recipe.yaml)"""
    recipe = os.path.join(metadata_dir, "..", "variants", "32_v1_recipe")

    args = [recipe]
    assert main_render.execute(args) == 0
