import os
import sys

import pytest
import conda.config as cc
from conda.compat import TemporaryDirectory

from conda_build.config import croot
from conda_build import api
from conda_build.utils import rm_rf
from .utils import metadata_dir, is_valid_dir

WORK_DIR = os.path.join(croot, 'work')


def test_render_need_download():
    # First get metadata with a recipe that is known to need a download:
    with pytest.raises(SystemExit):
        metadata, need_download = api.render(os.path.join(metadata_dir, "source_git_jinja2"),
                                             no_download_source=True)
    metadata, need_download = api.render(os.path.join(metadata_dir, "source_git_jinja2"),
                                         no_download_source=False)
    assert not need_download
    assert metadata.meta["package"]["version"] == "1.8.1"


def test_render_yaml_output():
    pass


def test_get_output_file_path():
    build_path = api.get_output_file_path(os.path.join(metadata_dir, "python_build"),
                                          no_download_source=True)
    assert build_path == os.path.join(sys.prefix, "conda-bld",
                                      cc.subdir, "conda-build-test-python-build-1.0-0.tar.bz2")
    build_path = api.get_output_file_path(os.path.join(metadata_dir, "python_build"),
                                          no_download_source=False)
    assert build_path == os.path.join(sys.prefix, "conda-bld",
                                      cc.subdir, "conda-build-test-python-build-1.0-0.tar.bz2")


def test_get_output_file_path_jinja2():
    rm_rf(WORK_DIR)
    # First get metadata with a recipe that is known to need a download:
    with pytest.raises(SystemExit):
        build_path = api.get_output_file_path(os.path.join(metadata_dir, "source_git_jinja2"),
                                              no_download_source=True)
    build_path = api.get_output_file_path(os.path.join(metadata_dir, "source_git_jinja2"),
                                          no_download_source=False)
    assert build_path == os.path.join(sys.prefix,
                            "conda-bld",
                            cc.subdir,
                            "conda-build-test-source-git-jinja2-1.8.1-py27_0_gf3d51ae.tar.bz2")


@pytest.fixture(params=[dirname for dirname in os.listdir(metadata_dir)
                        if is_valid_dir(metadata_dir, dirname)])
def recipe(request):
    return os.path.join(metadata_dir, request.param)


def test_recipe_builds(recipe):
    # These variables are defined solely for testing purposes,
    # so they can be checked within build scripts
    os.environ["CONDA_TEST_VAR"] = "conda_test"
    os.environ["CONDA_TEST_VAR_2"] = "conda_test_2"

    api.build(recipe, verbose=True)


def test_skeletonize_auto():
    with TemporaryDirectory() as tmp:
        api.skeletonize("sympy", output_dir=tmp)
        assert os.path.isdir(os.path.join(tmp, "sympy"))
