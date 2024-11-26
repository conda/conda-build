# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from conda.exceptions import PackagesNotFoundError

from conda_build import api
from conda_build.cli import main_build, main_render
from conda_build.config import (
    Config,
    zstd_compression_level_default,
)
from conda_build.exceptions import CondaBuildUserError, DependencyNeedsBuildingError
from conda_build.os_utils.external import find_executable
from conda_build.utils import get_build_folders, on_win, package_has_file

from ..utils import metadata_dir
from ..utils import reset_config as _reset_config

if TYPE_CHECKING:
    from pytest import FixtureRequest, MonkeyPatch
    from pytest_mock import MockerFixture

    from conda_build.metadata import MetaData

# FUTURE: Remove after 25.1
DEFAULT_PACKAGE_FORMAT_FLAG = "--package-format=1"


@pytest.mark.sanity
def test_build_empty_sections(conda_build_test_recipe_envvar: str):
    args = [
        "--no-anaconda-upload",
        os.path.join(metadata_dir, "empty_sections"),
        "--no-activate",
        "--no-anaconda-upload",
        DEFAULT_PACKAGE_FORMAT_FLAG,
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
        DEFAULT_PACKAGE_FORMAT_FLAG,
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
        DEFAULT_PACKAGE_FORMAT_FLAG,
    ]
    with pytest.raises(DependencyNeedsBuildingError):
        main_build.execute(args)


def test_no_filename_hash(testing_workdir, testing_metadata, capfd):
    api.output_yaml(testing_metadata, "meta.yaml")
    args = ["--output", testing_workdir, "--old-build-string"]
    main_render.execute(args)
    output, error = capfd.readouterr()
    assert not re.search("h[0-9a-f]{%d}" % testing_metadata.config.hash_length, output)  # noqa: UP031

    args = [
        "--no-anaconda-upload",
        "--no-activate",
        testing_workdir,
        "--old-build-string",
        DEFAULT_PACKAGE_FORMAT_FLAG,
    ]
    main_build.execute(args)
    output, error = capfd.readouterr()
    assert not re.search(
        "test_no_filename_hash.*h[0-9a-f]{%d}" % testing_metadata.config.hash_length,  # noqa: UP031
        output,
    )
    assert not re.search(
        "test_no_filename_hash.*h[0-9a-f]{%d}" % testing_metadata.config.hash_length,  # noqa: UP031
        error,
    )


def test_build_output_build_path(
    testing_workdir, testing_metadata, testing_config, capfd
):
    api.output_yaml(testing_metadata, "meta.yaml")
    testing_config.verbose = False
    testing_config.debug = False
    args = ["--output", testing_workdir, DEFAULT_PACKAGE_FORMAT_FLAG]
    main_build.execute(args)
    test_path = os.path.join(
        testing_config.croot,
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
    args = ["--output", testing_workdir, skip_recipe, DEFAULT_PACKAGE_FORMAT_FLAG]

    main_build.execute(args)

    test_path = lambda pkg: os.path.join(
        testing_config.croot, testing_config.host_subdir, pkg
    )
    test_paths = [
        test_path("test_build_output_build_path_multiple_recipes-1.0-1.tar.bz2"),
    ]

    output, error = capfd.readouterr()
    # assert error == ""
    assert output.rstrip().splitlines() == test_paths, error


def test_slash_in_recipe_arg_keeps_build_id(
    testing_workdir: str, testing_config: Config
):
    args = [
        os.path.join(metadata_dir, "has_prefix_files"),
        "--croot",
        testing_config.croot,
        "--no-anaconda-upload",
        DEFAULT_PACKAGE_FORMAT_FLAG,
    ]
    main_build.execute(args)

    output = os.path.join(
        testing_config.croot,
        testing_config.host_subdir,
        "conda-build-test-has-prefix-files-1.0-0.tar.bz2",
    )
    data = package_has_file(output, "binary-has-prefix", refresh_mode="forced")
    assert data
    if hasattr(data, "decode"):
        data = data.decode("UTF-8")
    assert "conda-build-test-has-prefix-files_1" in data


@pytest.mark.sanity
@pytest.mark.skipif(on_win, reason="prefix is always short on win.")
def test_build_long_test_prefix_default_enabled(mocker, testing_workdir):
    recipe_path = os.path.join(metadata_dir, "_test_long_test_prefix")
    args = [recipe_path, "--no-anaconda-upload", DEFAULT_PACKAGE_FORMAT_FLAG]
    main_build.execute(args)

    args.append("--no-long-test-prefix")
    with pytest.raises(CondaBuildUserError):
        main_build.execute(args)


def test_build_no_build_id(testing_workdir: str, testing_config: Config):
    args = [
        os.path.join(metadata_dir, "has_prefix_files"),
        "--no-build-id",
        "--croot",
        testing_config.croot,
        "--no-activate",
        "--no-anaconda-upload",
        DEFAULT_PACKAGE_FORMAT_FLAG,
    ]
    main_build.execute(args)

    output = os.path.join(
        testing_config.croot,
        testing_config.host_subdir,
        "conda-build-test-has-prefix-files-1.0-0.tar.bz2",
    )
    data = package_has_file(output, "binary-has-prefix", refresh_mode="forced")
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
    args = ["--no-anaconda-upload", "recipe1", "recipe2", DEFAULT_PACKAGE_FORMAT_FLAG]
    main_build.execute(args)


def test_build_output_folder(testing_workdir: str, testing_metadata: MetaData):
    api.output_yaml(testing_metadata, "meta.yaml")

    out = Path(testing_workdir, "out")
    out.mkdir(parents=True)

    args = [
        testing_workdir,
        "--no-build-id",
        "--croot",
        testing_workdir,
        "--no-activate",
        "--no-anaconda-upload",
        "--output-folder",
        str(out),
        DEFAULT_PACKAGE_FORMAT_FLAG,
    ]
    main_build.execute(args)

    assert (
        out / testing_metadata.config.host_subdir / testing_metadata.pkg_fn()
    ).is_file()


def test_build_source(testing_workdir: str):
    args = [
        os.path.join(metadata_dir, "_pyyaml_find_header"),
        "--source",
        "--no-build-id",
        "--croot",
        testing_workdir,
        "--no-activate",
        "--no-anaconda-upload",
        DEFAULT_PACKAGE_FORMAT_FLAG,
    ]
    main_build.execute(args)
    assert Path(testing_workdir, "work", "setup.py").is_file()


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
def test_purge_all(
    testing_workdir: str, testing_metadata: MetaData, tmp_path: Path
) -> None:
    """
    purge-all clears out build folders as well as build packages in the osx-64 folders and such
    """
    api.output_yaml(testing_metadata, "meta.yaml")
    testing_metadata.config.croot = str(tmp_path)
    outputs = api.build(testing_workdir, config=testing_metadata.config, notest=True)
    args = ["purge-all", f"--croot={tmp_path}"]
    main_build.execute(args)
    assert not get_build_folders(testing_metadata.config.croot)
    assert not any(os.path.isfile(fn) for fn in outputs)


@pytest.mark.serial
def test_no_force_upload(
    mocker: MockerFixture,
    monkeypatch: MonkeyPatch,
    testing_workdir: str | os.PathLike | Path,
    testing_metadata: MetaData,
    request: FixtureRequest,
):
    # this is nearly identical to tests/test_api_build.py::test_no_force_upload
    # only difference is this tests `conda_build.cli.main_build.execute`
    request.addfinalizer(_reset_config)
    call = mocker.patch("subprocess.call")
    anaconda = find_executable("anaconda")

    # render recipe
    api.output_yaml(testing_metadata, "meta.yaml")
    pkg = api.get_output_file_paths(testing_metadata)

    # mock Config.set_keys to always set anaconda_upload to True
    # conda's Context + conda_build's MetaData & Config objects interact in such an
    # awful way that mocking these configurations is ugly and confusing, all of it
    # needs major refactoring
    set_keys = Config.set_keys  # store original method
    monkeypatch.setattr(
        Config,
        "set_keys",
        lambda self, **kwargs: set_keys(self, **{**kwargs, "anaconda_upload": True}),
    )

    # check for normal upload
    main_build.execute(
        ["--no-force-upload", testing_workdir, DEFAULT_PACKAGE_FORMAT_FLAG]
    )
    call.assert_called_once_with([anaconda, "upload", *pkg])
    call.reset_mock()

    # check for force upload
    main_build.execute([testing_workdir, DEFAULT_PACKAGE_FORMAT_FLAG])
    call.assert_called_once_with([anaconda, "upload", "--force", *pkg])


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
    args = ["--no-anaconda-upload", empty_sections, DEFAULT_PACKAGE_FORMAT_FLAG]
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
    args = [
        "--no-anaconda-upload",
        "--croot",
        testing_workdir,
        empty_sections,
        DEFAULT_PACKAGE_FORMAT_FLAG,
    ]
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
    args = ["-t", output, DEFAULT_PACKAGE_FORMAT_FLAG]
    main_build.execute(args)


def test_activate_scripts_not_included(testing_workdir):
    recipe = os.path.join(metadata_dir, "_activate_scripts_not_included")
    args = [
        "--no-anaconda-upload",
        "--croot",
        testing_workdir,
        recipe,
        DEFAULT_PACKAGE_FORMAT_FLAG,
    ]
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


def test_relative_path_croot(
    conda_build_test_recipe_envvar: str, testing_config: Config
):
    # this tries to build a package while specifying the croot with a relative path:
    # conda-build --no-test --croot ./relative/path
    empty_sections = Path(metadata_dir, "empty_with_build_script")
    croot = Path(".", "relative", "path")

    args = [
        "--no-anaconda-upload",
        f"--croot={croot}",
        str(empty_sections),
        DEFAULT_PACKAGE_FORMAT_FLAG,
    ]
    main_build.execute(args)

    assert len(list(croot.glob("**/*.tar.bz2"))) == 1
    assert (
        croot / testing_config.subdir / "empty_with_build_script-0.0-0.tar.bz2"
    ).is_file()


def test_relative_path_test_artifact(
    conda_build_test_recipe_envvar: str, testing_config: Config
):
    # this test builds a package into (cwd)/relative/path and then calls:
    # conda-build --test ./relative/path/{platform}/{artifact}.tar.bz2
    empty_sections = Path(metadata_dir, "empty_with_build_script")
    croot_rel = Path(".", "relative", "path")
    croot_abs = croot_rel.resolve()

    # build the package
    args = [
        "--no-anaconda-upload",
        "--no-test",
        f"--croot={croot_abs}",
        str(empty_sections),
        DEFAULT_PACKAGE_FORMAT_FLAG,
    ]
    main_build.execute(args)

    assert len(list(croot_abs.glob("**/*.tar.bz2"))) == 1

    # run the test stage with relative path
    args = [
        "--no-anaconda-upload",
        "--test",
        os.path.join(
            croot_rel,
            testing_config.subdir,
            "empty_with_build_script-0.0-0.tar.bz2",
        ),
        DEFAULT_PACKAGE_FORMAT_FLAG,
    ]
    main_build.execute(args)


def test_test_extra_dep(testing_metadata):
    testing_metadata.meta["test"]["imports"] = ["imagesize"]
    api.output_yaml(testing_metadata, "meta.yaml")
    output = api.build(testing_metadata, notest=True, anaconda_upload=False)[0]

    # tests version constraints.  CLI would quote this - "click <6.7"
    args = [output, "-t", "--extra-deps", "imagesize <1.0", DEFAULT_PACKAGE_FORMAT_FLAG]
    # extra_deps will add it in
    main_build.execute(args)

    # missing click dep will fail tests
    with pytest.raises(CondaBuildUserError):
        args = [output, "-t", DEFAULT_PACKAGE_FORMAT_FLAG]
        # extra_deps will add it in
        main_build.execute(args)


@pytest.mark.parametrize(
    "additional_args, is_long_test_prefix",
    [([], True), (["--long-test-prefix"], True), (["--no-long-test-prefix"], False)],
)
def test_long_test_prefix(additional_args, is_long_test_prefix):
    args = ["non_existing_recipe", DEFAULT_PACKAGE_FORMAT_FLAG] + additional_args
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
    args = ["non_existing_recipe", DEFAULT_PACKAGE_FORMAT_FLAG]
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

    main_build.parse_args([str(recipe), DEFAULT_PACKAGE_FORMAT_FLAG])
    assert (
        f"RECIPE_PATH received is a file ({recipe}).\n"
        "It should be a path to a folder.\n"
        "Forcing conda-build to use the recipe file."
    ) == str(recwarn.pop(UserWarning).message)

    main_build.parse_args([str(dir_recipe_path), DEFAULT_PACKAGE_FORMAT_FLAG])
    assert not recwarn.list


def test_build_with_empty_channel_fails(empty_channel: Path) -> None:
    with pytest.raises(PackagesNotFoundError):
        main_build.execute(
            [
                "--override-channels",
                f"--channel={empty_channel}",
                os.path.join(metadata_dir, "_recipe_requiring_external_channel"),
                DEFAULT_PACKAGE_FORMAT_FLAG,
            ]
        )
