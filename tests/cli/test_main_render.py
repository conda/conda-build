# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys

import pytest
import yaml

from conda_build import api
from conda_build.cli import main_render
from conda_build.conda_interface import TemporaryDirectory

from ..utils import metadata_dir


def test_render_add_channel():
    """This recipe requires the conda_build_test_requirement package, which is
    only on the conda_build_test channel. This verifies that the -c argument
    works for rendering."""
    with TemporaryDirectory() as tmpdir:
        rendered_filename = os.path.join(tmpdir, "out.yaml")
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
            "rendering, but got only {}".format(required_package_details)
        )
        assert (
            required_package_details[1] == "1.0"
        ), f"Expected version number 1.0 on successful rendering, but got {required_package_details[1]}"


def test_render_without_channel_fails(tmp_path):
    # do make extra channel available, so the required package should not be found
    rendered_filename = tmp_path / "out.yaml"
    args = [
        "--override-channels",
        os.path.join(metadata_dir, "_recipe_requiring_external_channel"),
        "--file",
        str(rendered_filename),
    ]
    main_render.execute(args)
    with open(rendered_filename) as rendered_file:
        rendered_meta = yaml.safe_load(rendered_file)
    required_package_string = [
        pkg
        for pkg in rendered_meta.get("requirements", {}).get("build", [])
        if "conda_build_test_requirement" in pkg
    ][0]
    assert (
        required_package_string == "conda_build_test_requirement"
    ), f"Expected to get only base package name because it should not be found, but got :{required_package_string}"


def test_render_output_build_path(testing_workdir, testing_metadata, capfd, caplog):
    api.output_yaml(testing_metadata, "meta.yaml")
    args = ["--output", testing_workdir]
    main_render.execute(args)
    test_path = os.path.join(
        sys.prefix,
        "conda-bld",
        testing_metadata.config.host_subdir,
        "test_render_output_build_path-1.0-1.tar.bz2",
    )
    output, error = capfd.readouterr()
    assert output.rstrip() == test_path, error
    assert error == ""


def test_render_output_build_path_and_file(
    testing_workdir, testing_metadata, capfd, caplog
):
    api.output_yaml(testing_metadata, "meta.yaml")
    rendered_filename = "out.yaml"
    args = ["--output", "--file", rendered_filename, testing_workdir]
    main_render.execute(args)
    test_path = os.path.join(
        sys.prefix,
        "conda-bld",
        testing_metadata.config.host_subdir,
        "test_render_output_build_path_and_file-1.0-1.tar.bz2",
    )
    output, error = capfd.readouterr()
    assert output.rstrip() == test_path, error
    assert error == ""
    with open(rendered_filename) as rendered_file:
        rendered_meta = yaml.safe_load(rendered_file)
    assert rendered_meta["package"]["name"] == "test_render_output_build_path_and_file"


def test_render_output_build_path_set_python(testing_workdir, testing_metadata, capfd):
    testing_metadata.meta["requirements"] = {"host": ["python"], "run": ["python"]}
    api.output_yaml(testing_metadata, "meta.yaml")
    # build the other major thing, whatever it is
    if sys.version_info.major == 3:
        version = "2.7"
    else:
        version = "3.5"

    api.output_yaml(testing_metadata, "meta.yaml")
    metadata = api.render(testing_workdir, python=version)[0][0]

    args = ["--output", testing_workdir, "--python", version]
    main_render.execute(args)

    _hash = metadata.hash_dependencies()
    test_path = (
        "test_render_output_build_path_set_python-1.0-py{}{}{}_1.tar.bz2".format(
            version.split(".")[0], version.split(".")[1], _hash
        )
    )
    output, error = capfd.readouterr()
    assert os.path.basename(output.rstrip()) == test_path, error


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
