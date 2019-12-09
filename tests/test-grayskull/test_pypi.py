import json
import os

import pytest

from conda_build.grayskull import Requirements
from conda_build.grayskull.pypi import PyPi


@pytest.fixture
def pypi_metadata():
    path_metadata = os.path.join(
        os.path.dirname(__file__), "data", "pypi_pytest_metadata.json"
    )
    with open(path_metadata) as f:
        return json.load(f)


def test_refresh(pypi_metadata):
    recipe = PyPi(name="pytest")
    exp_req = Requirements(
        host={
            "python",
            "pip",
        },
        run={
            "python",
            "py >=1.5.0",
            "packaging",
            "attrs >=17.4.0",
            "more-itertools >=4.0.0",
            "pluggy <1.0,>=0.12",
            "wcwidth",
            "pathlib2 >=2.2.0  # [py<36]",
            "importlib-metadata >=0.12  # [py<38]",
            "atomicwrites >=1.0  # [win]",
            "colorama  # [win]",
        }
    )
    assert recipe._extract_pypi_requirements(pypi_metadata) == exp_req


def test_get_selector():
    assert PyPi._get_selector("sys_platform", "==", "win32") == "  # [win]"
    assert PyPi._get_selector("python_version", "<", "3.6") == "  # [py<36]"
