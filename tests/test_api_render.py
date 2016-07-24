import os

import pytest

from conda_build import api

from .utils import testing_workdir, test_config, metadata_dir, subdir


def test_render_need_download(testing_workdir, test_config):
    # First get metadata with a recipe that is known to need a download:
    with pytest.raises(SystemExit):
        metadata, need_download, need_reparse_in_env = api.render(
            os.path.join(metadata_dir, "source_git_jinja2"),
            config=test_config,
            no_download_source=True)
    metadata, need_download, need_reparse_in_env = api.render(
        os.path.join(metadata_dir, "source_git_jinja2"),
        config=test_config)
    assert not need_download
    assert metadata.meta["package"]["version"] == "1.8.1"


def test_render_yaml_output(testing_workdir, test_config):
    metadata, need_download, need_reparse_in_env = api.render(
        os.path.join(metadata_dir, "source_git_jinja2"),
        config=test_config)
    yaml_metadata = api.output_yaml(metadata)
    assert "package:" in yaml_metadata

    # writes file with yaml data in it
    api.output_yaml(metadata, os.path.join(testing_workdir, "output.yaml"))
    assert "package:" in open(os.path.join(testing_workdir, "output.yaml")).read()


def test_get_output_file_path(testing_workdir, test_config):
    build_path = api.get_output_file_path(os.path.join(metadata_dir, "python_build"),
                                          config=test_config,
                                          no_download_source=True)
    assert build_path == os.path.join(test_config.croot, subdir,
                                      "conda-build-test-python-build-1.0-0.tar.bz2")
    build_path = api.get_output_file_path(os.path.join(metadata_dir, "python_build"),
                                          config=test_config)
    assert build_path == os.path.join(test_config.croot, subdir,
                                      "conda-build-test-python-build-1.0-0.tar.bz2")


def test_get_output_file_path_jinja2(testing_workdir, test_config):
    # If this test does not raise, it's an indicator that the workdir is not
    #    being cleaned as it should.

    # First get metadata with a recipe that is known to need a download:
    with pytest.raises(SystemExit):
        build_path = api.get_output_file_path(os.path.join(metadata_dir, "source_git_jinja2"),
                                              config=test_config,
                                              no_download_source=True)
    build_path = api.get_output_file_path(os.path.join(metadata_dir, "source_git_jinja2"),
                                          config=test_config)
    assert build_path == os.path.join(test_config.croot, subdir,
                                      "conda-build-test-source-git-jinja2-1.8.1-"
                                      "py{0}_0_gf3d51ae.tar.bz2".format(test_config.CONDA_PY))
