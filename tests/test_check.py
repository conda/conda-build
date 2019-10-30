import os

from conda_build import api
from .utils import metadata_dir


def test_check_multiple_sources():
    recipe = os.path.join(metadata_dir, "multiple_sources")
    assert api.check(recipe)
