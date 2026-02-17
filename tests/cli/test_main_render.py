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

from ..utils import metadata_dir

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture

    from conda_build.metadata import MetaData


def test_render_add_channel(tmp_path: Path) -> None:
    """This recipe requires the conda_build_test_requirement package, which is
    only on the conda_build_test channel. This verifies that the -c argument
    works for rendering."""
    rendered_filename = os.path.join(tmp_path, "out.yaml")
    args = [
        "-c",
        "conda_build_test",
        os.path.join(metadata_dir, "_recipe_requiring_external_channel"),
        "--file",
        rendered_filename,
    ]
    main_render.execute(args)
    with open(rendered_filename) as rendered_file:
        rendered_meta = yaml.safe_load(rendered_file)
    required_package_string = [
        pkg
        for pkg in rendered_meta["requirements"]["build"]
        if "conda_build_test_requirement" in pkg
    ][0]
    required_package_details = required_package_string.split(" ")
    assert len(required_package_details) > 1, (
        "Expected version number on successful "
        f"rendering, but got only {required_package_details}"
    )
    assert required_package_details[1] == "1.0", (
        f"Expected version number 1.0 on successful rendering, but got {required_package_details[1]}"
    )


def test_render_with_empty_channel_fails(tmp_path: Path, empty_channel: Path) -> None:
    with pytest.raises(PackagesNotFoundError):
        main_render.execute(
            [
                "--override-channels",
                f"--channel={empty_channel}",
                os.path.join(metadata_dir, "_recipe_requiring_external_channel"),
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
