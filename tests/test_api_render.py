"""
This module tests the test API.  These are high-level integration tests.  Lower level unit tests
should go in test_render.py
"""

import os

import mock
import pytest

from conda_build import api

from .utils import testing_workdir, test_config, metadata_dir, test_metadata


def test_render_need_download(testing_workdir, test_config):
    # first, test that the download/render system renders all it can,
    #    and accurately returns its needs
    with pytest.raises(SystemExit):
        metadata, need_download, need_reparse_in_env = api.render(
            os.path.join(metadata_dir, "source_git_jinja2"),
            config=test_config,
            no_download_source=True)
        assert need_download
        assert need_reparse_in_env

    # Test that allowing source download lets it to the right thing.
    metadata, need_download, need_reparse_in_env = api.render(
        os.path.join(metadata_dir, "source_git_jinja2"),
        config=test_config,
        no_download_source=False)
    assert not need_download
    assert metadata.meta["package"]["version"] == "1.20.2"


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
    assert build_path == os.path.join(test_config.croot, test_config.subdir,
                                      "conda-build-test-python-build-1.0-0.tar.bz2")
    build_path = api.get_output_file_path(os.path.join(metadata_dir, "python_build"),
                                          config=test_config)
    assert build_path == os.path.join(test_config.croot, test_config.subdir,
                                      "conda-build-test-python-build-1.0-0.tar.bz2")


def test_get_output_file_path_metadata_object(test_config, test_metadata):
    build_path = api.get_output_file_path(test_metadata)
    assert build_path == os.path.join(test_config.croot, test_config.subdir,
        "test_get_output_file_path_metadata_object-1.0-py{}_1.tar.bz2".format(test_config.CONDA_PY))


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
    assert build_path == os.path.join(test_config.croot, test_config.subdir,
                                      "conda-build-test-source-git-jinja2-1.20.2-"
                                      "py{0}_0_g262d444.tar.bz2".format(test_config.CONDA_PY))


@mock.patch('conda_build.source')
def test_output_without_jinja_does_not_download(mock_source, testing_workdir, test_config):
        api.get_output_file_path(os.path.join(metadata_dir, "source_git"),
                                              config=test_config)
        mock_source.provide.assert_not_called()
