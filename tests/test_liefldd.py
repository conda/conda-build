from glob import glob
import json
import os
import pytest
import re
import sys

from conda_build.render import finalize_metadata
from conda_build.conda_interface import subdir
from conda_build import api, utils

from .utils import liefldd_dir, is_valid_dir


@pytest.fixture(params=[dirname for dirname in os.listdir(liefldd_dir)
                        if is_valid_dir(liefldd_dir, dirname)])
def recipe(request):
    return os.path.join(liefldd_dir, request.param)


@pytest.mark.slow
def test_liefldd_recipes(recipe, testing_config):
    testing_config.activate = True
    testing_config.error_overlinking = True
    testing_config.prefix_length = 40
    api.build(recipe, config=testing_config)
