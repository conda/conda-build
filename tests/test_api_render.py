"""
This module tests the test API.  These are high-level integration tests.  Lower level unit tests
should go in test_render.py
"""

import os

import mock
import pytest

from conda_build import api

from .utils import metadata_dir


def test_render_need_download(testing_workdir, testing_config):
    # first, test that the download/render system renders all it can,
    #    and accurately returns its needs

    with pytest.raises((ValueError, SystemExit)):
        metadata, need_download, need_reparse_in_env = api.render(
            os.path.join(metadata_dir, "source_git_jinja2"),
            config=testing_config,
            no_download_source=True)[0]
        assert need_download
        assert need_reparse_in_env

    # Test that allowing source download lets it to the right thing.
    metadata, need_download, need_reparse_in_env = api.render(
        os.path.join(metadata_dir, "source_git_jinja2"),
        config=testing_config,
        no_download_source=False)[0]
    assert not need_download
    assert metadata.meta["package"]["version"] == "1.20.2"


def test_render_yaml_output(testing_workdir, testing_config):
    metadata, need_download, need_reparse_in_env = api.render(
        os.path.join(metadata_dir, "source_git_jinja2"),
        config=testing_config)[0]
    yaml_metadata = api.output_yaml(metadata)
    assert "package:" in yaml_metadata

    # writes file with yaml data in it
    api.output_yaml(metadata, os.path.join(testing_workdir, "output.yaml"))
    assert "package:" in open(os.path.join(testing_workdir, "output.yaml")).read()


def test_get_output_file_path(testing_workdir, testing_metadata):
    api.output_yaml(testing_metadata, 'meta.yaml')

    build_path = api.get_output_file_path(testing_workdir,
                                          config=testing_metadata.config,
                                          no_download_source=True)[0]
    _hash = testing_metadata._hash_dependencies()
    python = ''.join(testing_metadata.config.variant['python'].split('.')[:2])
    assert build_path == os.path.join(testing_metadata.config.croot, testing_metadata.config.host_subdir,
                                      "test_get_output_file_path-1.0-py{}{}_1.tar.bz2".format(
                                          python, _hash))


def test_get_output_file_path_metadata_object(testing_metadata):
    build_path = api.get_output_file_path(testing_metadata)[0]
    _hash = testing_metadata._hash_dependencies()
    python = ''.join(testing_metadata.config.variant['python'].split('.')[:2])
    assert build_path == os.path.join(testing_metadata.config.croot, testing_metadata.config.host_subdir,
                "test_get_output_file_path_metadata_object-1.0-py{}{}_1.tar.bz2".format(
                    python, _hash))


def test_get_output_file_path_jinja2(testing_workdir, testing_config):
    # If this test does not raise, it's an indicator that the workdir is not
    #    being cleaned as it should.

    # First get metadata with a recipe that is known to need a download:
    with pytest.raises((ValueError, SystemExit)):
        build_path = api.get_output_file_path(os.path.join(metadata_dir, "source_git_jinja2"),
                                              config=testing_config,
                                              no_download_source=True)[0]
    metadata, need_download, need_reparse_in_env = api.render(
        os.path.join(metadata_dir, "source_git_jinja2"),
        config=testing_config,
        no_download_source=False)[0]
    build_path = api.get_output_file_path(metadata)[0]
    _hash = metadata._hash_dependencies()
    python = ''.join(metadata.config.variant['python'].split('.')[:2])
    assert build_path == os.path.join(testing_config.croot, testing_config.host_subdir,
                                      "conda-build-test-source-git-jinja2-1.20.2-"
                                      "py{0}{1}_0_g262d444.tar.bz2".format(python, _hash))


@mock.patch('conda_build.source')
def test_output_without_jinja_does_not_download(mock_source, testing_workdir, testing_config):
        api.get_output_file_path(os.path.join(metadata_dir, "source_git"),
                                              config=testing_config)[0]
        mock_source.provide.assert_not_called()


def test_pin_compatible_semver(testing_config):
    recipe_dir = os.path.join(metadata_dir, '_pin_compatible')
    metadata = api.render(recipe_dir, config=testing_config)[0][0]
    assert 'numpy >=1.11.2,1.11.*' in metadata.get_value('requirements/run')
    # not terribly important, but might be nice for continuity's sake
    #    This is broken right now, because compound pins like we do here have never been supported
    #    in the build string.
    # assert 'np111' in api.get_output_file_path(metadata)
