import os
import subprocess
import sys

from conda_build.conda_interface import PY3

from .utils import subdir

thisdir = os.path.dirname(os.path.realpath(__file__))
metadata_dir = os.path.join(thisdir, "test-recipes/metadata")


# no tests here - this is tested at a high level in test_cli.py and in test_api_render.py.
#   tests here should be lower-level unit tests of the render.py functionality.
