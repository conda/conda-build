# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import re
import sys

import pytest

import conda_build
from conda_build import api
from conda_build.cli import main_build, main_render
from conda_build.conda_interface import (
    TemporaryDirectory,
    cc_conda_build,
    context,
    reset_context,
)
from conda_build.config import Config, zstd_compression_level_default
from conda_build.exceptions import DependencyNeedsBuildingError
from conda_build.utils import get_build_folders, on_win, package_has_file

from ..utils import metadata_dir


def _reset_config(search_path=None):
    reset_context(search_path)
    cc_conda_build.clear()
    cc_conda_build.update(
        context.conda_build if hasattr(context, "conda_build") else {}
    )


@pytest.mark.sanity
def test_build_empty_sections(conda_build_test_recipe_envvar: str):
    args = [
        "--no-anaconda-upload",
        os.path.join(metadata_dir, "empty_sections"),
        "--no-activate",
        "--no-anaconda-upload",
    ]
    main_build.execute(args)


@pytest.mark.serial
def test_build_add_channel():
    """This recipe requires the conda_build_test_requirement package, which is
    only on the conda_build_test channel. This verifies that the -c argument
    works."""

    args = [
        "-c",
        "conda_build_test",
        "--no-activate",
        "--no-anaconda-upload",
        os.path.join(metadata_dir, "_recipe_requiring_external_channel"),
    ]
    main_build.execute(args)


def test_build_without_channel_fails(testing_workdir):
    # remove the conda forge channel from the arguments and make sure that we fail.  If we don't,
    #    we probably have channels in condarc, and this is not a good test.
    args = [
        "--no-anaconda-upload",
        "--no-activate",
        os.path.join(metadata_dir, "_recipe_requiring_external_channel"),
    ]
    with pytest.raises(DependencyNeedsBuildingError):
        main_build.execute(args)


def test_no_filename_hash(testing_workdir, testing_metadata, capfd):
    api.output_yaml(testing_metadata, "meta.yaml")
    args = ["--output", testing_workdir, "--old-build-string"]
    main_render.execute(args)
    output, error = capfd.readouterr()
    assert not re.search("h[0-9a-f]{%d}" % testing_metadata.config.hash_length, output)

    args = [
        "--no-anaconda-upload",
        "--no-activate",
        testing_workdir,
        "--old-build-string",
    ]
    main_build.execute(args)
    output, error = capfd.readouterr()
    assert not re.search(
        "test_no_filename_hash.*h[0-9a-f]{%d}" % testing_metadata.config.hash_length,
        output,
    )
    assert not re.search(
        "test_no_filename_hash.*h[0-9a-f]{%d}" % testing_metadata.config.hash_length,
        error,
    )


def test_build_output_build_path(
    testing_workdir, testing_metadata, testing_config, capfd
):
    api.output_yaml(testing_metadata, "meta.yaml")
    testing_config.verbose = False
    testing_config.debug = False
    args = ["--output", testing_workdir]
    main_build.execute(args)
    test_path = os.path.join(
        sys.prefix,
        "conda-bld",
        testing_config.host_subdir,
        "test_build_output_build_path-1.0-1.tar.bz2",
    )
    output, error = capfd.readouterr()
    assert test_path == output.rstrip(), error
    assert error == ""


def test_build_output_build_path_multiple_recipes(
    testing_workdir, testing_metadata, testing_config, capfd
):
    api.output_yaml(testing_metadata, "meta.yaml")
    testing_config.verbose = False
    skip_recipe = os.path.join(metadata_dir, "build_skip")
    args = ["--output", testing_workdir, skip_recipe]

    main_build.execute(args)

    test_path = lambda pkg: os.path.join(
        sys.prefix, "conda-bld", testing_config.host_subdir, pkg
    )
    test_paths = [
        test_path("test_build_output_build_path_multiple_recipes-1.0-1.tar.bz2"),
    ]

    output, error = capfd.readouterr()
    # assert error == ""
    assert output.rstrip().splitlines() == test_paths, error


def test_slash_in_recipe_arg_keeps_build_id(testing_workdir, testing_config):
    args = [
        os.path.join(metadata_dir, "has_prefix_files"),
        "--croot",
        testing_config.croot,
        "--no-anaconda-upload",
    ]
    outputs = main_build.execute(args)
    data = package_has_file(outputs[0], "binary-has-prefix", refresh_mode="forced")
    assert data
    if hasattr(data, "decode"):
        data = data.decode("UTF-8")
    assert "conda-build-test-has-prefix-files_1" in data


@pytest.mark.sanity
@pytest.mark.skipif(on_win, reason="prefix is always short on win.")
def test_build_long_test_prefix_default_enabled(mocker, testing_workdir):
    recipe_path = os.path.join(metadata_dir, "_test_long_test_prefix")
    args = [recipe_path, "--no-anaconda-upload"]
    main_build.execute(args)

    args.append("--no-long-test-prefix")
    with pytest.raises(SystemExit):
        main_build.execute(args)


def test_build_no_build_id(testing_workdir, testing_config):
    args = [
        os.path.join(metadata_dir, "has_prefix_files"),
        "--no-build-id",
        "--croot",
        testing_config.croot,
        "--no-activate",
        "--no-anaconda-upload",
    ]
    outputs = main_build.execute(args)
    data = package_has_file(outputs[0], "binary-has-prefix", refresh_mode="forced")
    assert data
    if hasattr(data, "decode"):
        data = data.decode("UTF-8")
    assert "has_prefix_files_1" not in data


def test_build_multiple_recipes(testing_metadata, testing_workdir, testing_config):
    """Test that building two recipes in one CLI call separates the build environment for each"""
    os.makedirs("recipe1")
    os.makedirs("recipe2")
    api.output_yaml(testing_metadata, "recipe1/meta.yaml")
    with open("recipe1/run_test.py", "w") as f:
        f.write(
            "import os; assert 'test_build_multiple_recipes' in os.getenv('PREFIX')"
        )
    testing_metadata.meta["package"]["name"] = "package2"
    api.output_yaml(testing_metadata, "recipe2/meta.yaml")
    with open("recipe2/run_test.py", "w") as f:
        f.write("import os; assert 'package2' in os.getenv('PREFIX')")
    args = ["--no-anaconda-upload", "recipe1", "recipe2"]
    main_build.execute(args)


def test_build_output_folder(testing_workdir, testing_metadata, capfd):
    api.output_yaml(testing_metadata, "meta.yaml")
    with TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "out")
        args = [
            testing_workdir,
            "--no-build-id",
            "--croot",
            tmp,
            "--no-activate",
            "--no-anaconda-upload",
            "--output-folder",
            out,
        ]
        output = main_build.execute(args)[0]
        assert os.path.isfile(
            os.path.join(
                out, testing_metadata.config.host_subdir, os.path.basename(output)
            )
        )


def test_build_source(testing_workdir):
    with TemporaryDirectory() as tmp:
        args = [
            os.path.join(metadata_dir, "_pyyaml_find_header"),
            "--source",
            "--no-build-id",
            "--croot",
            tmp,
            "--no-activate",
            "--no-anaconda-upload",
        ]
        main_build.execute(args)
        assert os.path.isfile(os.path.join(tmp, "work", "setup.py"))


@pytest.mark.serial
def test_purge(testing_workdir, testing_metadata):
    """
    purge clears out build folders - things like some_pkg_12048309850135

    It does not clear out build packages from folders like osx-64 or linux-64.
    """
    api.output_yaml(testing_metadata, "meta.yaml")
    outputs = api.build(testing_workdir, notest=True)
    args = ["purge"]
    main_build.execute(args)
    dirs = get_build_folders(testing_metadata.config.croot)
    assert not dirs
    # make sure artifacts are kept - only temporary folders get nuked
    assert all(os.path.isfile(fn) for fn in outputs)


@pytest.mark.serial
def test_purge_all(testing_workdir, testing_metadata):
    """
    purge-all clears out build folders as well as build packages in the osx-64 folders and such
    """
    api.output_yaml(testing_metadata, "meta.yaml")
    with TemporaryDirectory() as tmpdir:
        testing_metadata.config.croot = tmpdir
        outputs = api.build(
            testing_workdir, config=testing_metadata.config, notest=True
        )
        args = ["purge-all", "--croot", tmpdir]
        main_build.execute(args)
        assert not get_build_folders(testing_metadata.config.croot)
        assert not any(os.path.isfile(fn) for fn in outputs)


@pytest.mark.serial
def test_no_force_upload(mocker, testing_workdir, testing_metadata, request):
    with open(os.path.join(testing_workdir, ".condarc"), "w") as f:
        f.write("anaconda_upload: True\n")
        f.write("conda_build:\n")
        f.write("    force_upload: False\n")
    del testing_metadata.meta["test"]
    api.output_yaml(testing_metadata, "meta.yaml")
    args = ["--no-force-upload", testing_workdir]
    call = mocker.patch.object(conda_build.build.subprocess, "call")
    request.addfinalizer(_reset_config)
    _reset_config([os.path.join(testing_workdir, ".condarc")])
    main_build.execute(args)
    pkg = api.get_output_file_path(testing_metadata)
    assert call.called_once_with(["anaconda", "upload", pkg])
    args = [testing_workdir]
    with open(os.path.join(testing_workdir, ".condarc"), "w") as f:
        f.write("anaconda_upload: True\n")
    main_build.execute(args)
    assert call.called_once_with(["anaconda", "upload", "--force", pkg])


@pytest.mark.slow
def test_conda_py_no_period(testing_workdir, testing_metadata, monkeypatch):
    monkeypatch.setenv("CONDA_PY", "36")
    testing_metadata.meta["requirements"] = {"host": ["python"], "run": ["python"]}
    api.output_yaml(testing_metadata, "meta.yaml")
    outputs = api.build(testing_workdir, notest=True)
    assert any("py36" in output for output in outputs)


def test_build_skip_existing(
    testing_workdir,
    capfd,
    mocker,
    conda_build_test_recipe_envvar: str,
):
    # build the recipe first
    empty_sections = os.path.join(metadata_dir, "empty_sections")
    args = ["--no-anaconda-upload", empty_sections]
    main_build.execute(args)
    args.insert(0, "--skip-existing")
    import conda_build.source

    provide = mocker.patch.object(conda_build.source, "provide")
    main_build.execute(args)
    provide.assert_not_called()
    output, error = capfd.readouterr()
    assert "are already built" in output or "are already built" in error


def test_build_skip_existing_croot(
    testing_workdir,
    capfd,
    conda_build_test_recipe_envvar: str,
):
    # build the recipe first
    empty_sections = os.path.join(metadata_dir, "empty_sections")
    args = ["--no-anaconda-upload", "--croot", testing_workdir, empty_sections]
    main_build.execute(args)
    args.insert(0, "--skip-existing")
    main_build.execute(args)
    output, error = capfd.readouterr()
    assert "are already built" in output


@pytest.mark.sanity
def test_package_test(testing_workdir, testing_metadata):
    """Test calling conda build -t <package file> - rather than <recipe dir>"""
    api.output_yaml(testing_metadata, "recipe/meta.yaml")
    output = api.build(testing_workdir, config=testing_metadata.config, notest=True)[0]
    args = ["-t", output]
    main_build.execute(args)


def test_activate_scripts_not_included(testing_workdir):
    recipe = os.path.join(metadata_dir, "_activate_scripts_not_included")
    args = ["--no-anaconda-upload", "--croot", testing_workdir, recipe]
    main_build.execute(args)
    out = api.get_output_file_paths(recipe, croot=testing_workdir)[0]
    for f in (
        "bin/activate",
        "bin/deactivate",
        "bin/conda",
        "Scripts/activate.bat",
        "Scripts/deactivate.bat",
        "Scripts/conda.bat",
        "Scripts/activate.exe",
        "Scripts/deactivate.exe",
        "Scripts/conda.exe",
        "Scripts/activate",
        "Scripts/deactivate",
        "Scripts/conda",
    ):
        assert not package_has_file(out, f)


def test_relative_path_croot(conda_build_test_recipe_envvar: str):
    # this tries to build a package while specifying the croot with a relative path:
    # conda-build --no-test --croot ./relative/path

    empty_sections = os.path.join(metadata_dir, "empty_with_build_script")
    croot_rel = os.path.join(".", "relative", "path")
    args = ["--no-anaconda-upload", "--croot", croot_rel, empty_sections]
    outputfile = main_build.execute(args)

    assert len(outputfile) == 1
    assert os.path.isfile(outputfile[0])


def test_relative_path_test_artifact(conda_build_test_recipe_envvar: str):
    # this test builds a package into (cwd)/relative/path and then calls:
    # conda-build --test ./relative/path/{platform}/{artifact}.tar.bz2

    empty_sections = os.path.join(metadata_dir, "empty_with_build_script")
    croot_rel = os.path.join(".", "relative", "path")
    croot_abs = os.path.abspath(os.path.normpath(croot_rel))

    # build the package
    args = ["--no-anaconda-upload", "--no-test", "--croot", croot_abs, empty_sections]
    output_file_abs = main_build.execute(args)
    assert len(output_file_abs) == 1

    output_file_rel = os.path.join(
        croot_rel, os.path.relpath(output_file_abs[0], croot_abs)
    )

    # run the test stage with relative path
    args = ["--no-anaconda-upload", "--test", output_file_rel]
    main_build.execute(args)


def test_relative_path_test_recipe(conda_build_test_recipe_envvar: str):
    # this test builds a package into (cwd)/relative/path and then calls:
    # conda-build --test --croot ./relative/path/ /abs/path/to/recipe

    empty_sections = os.path.join(metadata_dir, "empty_with_build_script")
    croot_rel = os.path.join(".", "relative", "path")
    croot_abs = os.path.abspath(os.path.normpath(croot_rel))

    # build the package
    args = ["--no-anaconda-upload", "--no-test", "--croot", croot_abs, empty_sections]
    output_file_abs = main_build.execute(args)
    assert len(output_file_abs) == 1

    # run the test stage with relative croot
    args = ["--no-anaconda-upload", "--test", "--croot", croot_rel, empty_sections]
    main_build.execute(args)


def test_test_extra_dep(testing_metadata):
    testing_metadata.meta["test"]["imports"] = ["imagesize"]
    api.output_yaml(testing_metadata, "meta.yaml")
    output = api.build(testing_metadata, notest=True, anaconda_upload=False)[0]

    # tests version constraints.  CLI would quote this - "click <6.7"
    args = [output, "-t", "--extra-deps", "imagesize <1.0"]
    # extra_deps will add it in
    main_build.execute(args)

    # missing click dep will fail tests
    with pytest.raises(SystemExit):
        args = [output, "-t"]
        # extra_deps will add it in
        main_build.execute(args)


@pytest.mark.parametrize(
    "additional_args, is_long_test_prefix",
    [([], True), (["--long-test-prefix"], True), (["--no-long-test-prefix"], False)],
)
def test_long_test_prefix(additional_args, is_long_test_prefix):
    args = ["non_existing_recipe"] + additional_args
    parser, args = main_build.parse_args(args)
    config = Config(**args.__dict__)
    assert config.long_test_prefix is is_long_test_prefix


@pytest.mark.serial
@pytest.mark.parametrize(
    "zstd_level_condarc, zstd_level_cli",
    [
        (None, None),
        (1, None),
        (1, 2),
    ],
)
def test_zstd_compression_level(
    testing_workdir, request, zstd_level_condarc, zstd_level_cli
):
    assert zstd_compression_level_default not in {zstd_level_condarc, zstd_level_cli}
    if zstd_level_condarc:
        with open(os.path.join(testing_workdir, ".condarc"), "w") as f:
            print(
                "conda_build:",
                f"  zstd_compression_level: {zstd_level_condarc}",
                sep="\n",
                file=f,
            )
    request.addfinalizer(_reset_config)
    _reset_config([os.path.join(testing_workdir, ".condarc")])
    args = ["non_existing_recipe"]
    if zstd_level_cli:
        args.append(f"--zstd-compression-level={zstd_level_cli}")
    parser, args = main_build.parse_args(args)
    config = Config(**args.__dict__)
    if zstd_level_cli:
        assert config.zstd_compression_level == zstd_level_cli
    elif zstd_level_condarc:
        assert config.zstd_compression_level == zstd_level_condarc
    else:
        assert config.zstd_compression_level == zstd_compression_level_default


def test_user_warning(tmpdir, recwarn):
    dir_recipe_path = tmpdir.mkdir("recipe-path")
    recipe = dir_recipe_path.join("meta.yaml")
    recipe.write("")

    main_build.parse_args([str(recipe)])
    assert (
        f"RECIPE_PATH received is a file ({recipe}).\n"
        "It should be a path to a folder.\n"
        "Forcing conda-build to use the recipe file."
    ) == str(recwarn.pop(UserWarning).message)

    main_build.parse_args([str(dir_recipe_path)])
    assert not recwarn.list
