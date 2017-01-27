"""
This module tests the test API.  These are high-level integration tests.
"""

import os

from conda_build import api
from .utils import metadata_dir


def test_package_test(testing_workdir, test_config):
    """Test calling conda build -t <package file> - rather than <recipe dir>"""

    # temporarily necessary because we have custom rebuilt svn for longer prefix here
    test_config.channel_urls = ('conda_build_test', )

    recipe = os.path.join(metadata_dir, 'has_prefix_files')
    api.build(recipe, config=test_config, notest=True)
    output_file = api.get_output_file_path(recipe, config=test_config)
    api.test(output_file, config=test_config)


def test_package_with_jinja2_does_not_redownload_source(testing_workdir, test_config):
    recipe = os.path.join(metadata_dir, 'jinja2_build_str')
    api.build(recipe, config=test_config, notest=True)
    output_file = api.get_output_file_path(recipe, config=test_config)
    # this recipe uses jinja2, which should trigger source download, except that source download
    #    will have already happened in the build stage.
    # https://github.com/conda/conda-build/issues/1451
    api.test(output_file, config=test_config)


def test_recipe_test(testing_workdir, test_config):
    # temporarily necessary because we have custom rebuilt svn for longer prefix here
    test_config.channel_urls = ('conda_build_test', )

    recipe = os.path.join(metadata_dir, 'has_prefix_files')
    api.build(recipe, config=test_config, notest=True)
    api.test(recipe, config=test_config)


def test_metadata_test(test_metadata):
    api.build(test_metadata, notest=True)
    api.test(test_metadata)
