"""
This module tests the test API.  These are high-level integration tests.
"""

import os
import sys

import pytest

from conda_build import api
from conda_build.source import download
from .utils import subdir, testing_workdir, metadata_dir, test_config

def test_package_test(testing_workdir, test_config):
    """Test calling conda build -t <package file> - rather than <recipe dir>"""

    # temporarily necessary because we have custom rebuilt svn for longer prefix here
    test_config.channel_urls = ('conda_build_test', )

    recipe = os.path.join(metadata_dir, 'has_prefix_files')
    api.build(recipe, config=test_config, notest=True)
    output_file = api.get_output_file_path(recipe, config=test_config)
    api.test(output_file, config=test_config)


def test_recipe_test(testing_workdir):
    pass
