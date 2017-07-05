"""
This module tests the test API.  These are high-level integration tests.
"""

import os

import pytest

from conda_build import api
from .utils import metadata_dir


def test_package_test(testing_workdir, testing_config):
    """Test calling conda build -t <package file> - rather than <recipe dir>"""
    recipe = os.path.join(metadata_dir, 'has_prefix_files')
    metadata = api.render(recipe, config=testing_config)[0][0]
    outputs = api.build(metadata, notest=True)
    api.test(outputs[0], config=metadata.config)


def test_package_test_without_recipe_in_package(testing_workdir, testing_metadata):
    """Can't test packages after building if recipe is not included.  Not enough info to go on."""
    testing_metadata.config.include_recipe = False
    output = api.build(testing_metadata, notest=True)[0]
    with pytest.raises(IOError):
        api.test(output, config=testing_metadata.config)


def test_package_with_jinja2_does_not_redownload_source(testing_workdir, testing_config, mocker):
    recipe = os.path.join(metadata_dir, 'jinja2_build_str')
    metadata = api.render(recipe, config=testing_config, dirty=True)[0][0]
    outputs = api.build(metadata, notest=True)
    # this recipe uses jinja2, which should trigger source download, except that source download
    #    will have already happened in the build stage.
    # https://github.com/conda/conda-build/issues/1451
    provide = mocker.patch('conda_build.source.provide')
    api.test(outputs[0], config=metadata.config)
    assert not provide.called
