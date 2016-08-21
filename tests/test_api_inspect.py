import os

from conda_build import api
from .utils import metadata_dir

thisdir = os.path.dirname(os.path.abspath(__file__))


def test_check_recipe():
    """Technically not inspect, but close enough to belong here"""
    assert api.check(os.path.join(metadata_dir, "source_git_jinja2"))


# These tests are already being done in test_cli.py.  If we have a better way to test, move here.
def test_inpect_linkages():
    pass


def test_inspect_objects():
    pass


def test_installable():
    pass
