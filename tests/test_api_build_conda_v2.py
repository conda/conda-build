import os
import pytest

from conda_build import api

from .utils import metadata_dir

@pytest.fixture()
def recipe():
    # Build the "entry_points" recipe, which contains a test pass for package.
    return os.path.join(metadata_dir, "entry_points")

@pytest.mark.parametrize("pkg_format,pkg_ext", [(None, ".tar.bz2"), ("2", ".conda")])
def test_conda_pkg_format(recipe, pkg_format, pkg_ext, testing_config, testing_workdir, monkeypatch):
    """Conda package format "2" builds .conda packages."""

    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    testing_config.activate = True
    testing_config.conda_pkg_format = pkg_format
    monkeypatch.setenv("CONDA_TEST_VAR", "conda_test")
    monkeypatch.setenv("CONDA_TEST_VAR_2", "conda_test_2")

    output_file, = api.get_output_file_paths(recipe, config=testing_config)
    assert output_file.endswith(pkg_ext)

    api.build(recipe, config=testing_config)
    assert os.path.exists(output_file)
