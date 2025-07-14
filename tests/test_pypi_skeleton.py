# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import pytest
from conda.auxlib.ish import dals

from conda_build.skeletons import pypi
from conda_build.skeletons.pypi import _formating_value, _print_dict


@pytest.mark.parametrize(
    "version,version_range",
    [
        ("2.2", " >=2.2,<3"),
        ("1.4.5", " >=1.4.5,<1.5"),
        ("2.2.post3", " >=2.2.post3,<3"),
        ("2.2.pre3", " >=2.2.pre3,<3"),
        ("1.4.5a4", " >=1.4.5a4,<1.5"),
        ("1.4.5b4", " >=1.4.5b4,<1.5"),
        ("1.4.5rc4", " >=1.4.5rc4,<1.5"),
        ("2.2.0", " >=2.2.0,<2.3"),
        ("1.4.5.0", " >=1.4.5.0,<1.4.6"),
    ],
)
def test_version_compare(version, version_range):
    assert pypi.convert_version(version) == version_range


@pytest.mark.parametrize(
    "name,value,result",
    [
        ("summary", "SUMMARY SUMMARY", ' "SUMMARY SUMMARY"\n'),
        ("description", "DESCRIPTION DESCRIPTION", ' "DESCRIPTION DESCRIPTION"\n'),
        ("script", "SCRIPT VALUE", ' "SCRIPT VALUE"\n'),
        ("name", "{{name|lower}}", ' "{{name|lower}}"\n'),
        ("name", "NORMAL NAME", " NORMAL NAME\n"),
    ],
)
def test_formating_value(name, value, result):
    assert _formating_value(name, value) == result


def test_print_dict():
    recipe_metadata = {
        "about": {
            "home": "https://conda.io",
            "license": "MIT",
            "license_family": "MIT",
            "summary": "SUMMARY SUMMARY SUMMARY",
            "description": "DESCRIPTION DESCRIPTION DESCRIPTION",
        },
        "source": {
            "sha256": "4d24b03ffa67638a3fa931c09fd9e0273ffa904e95ebebe7d4b1a54c93d7b732",
            "url": "https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz",
        },
        "package": {
            "name": "{{ name|lower }}",
            "version": "{{ version }}",
        },
        "build": {
            "number": 0,
            "script": "{{ PYTHON }} -m pip install . -vv",
        },
    }
    recipe_order = ["package", "source", "build", "about"]
    recipe_yaml = dals(
        """
        package:
          name: "{{ name|lower }}"
          version: "{{ version }}"

        source:
          sha256: 4d24b03ffa67638a3fa931c09fd9e0273ffa904e95ebebe7d4b1a54c93d7b732
          url: "https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz"

        build:
          number: 0
          script: "{{ PYTHON }} -m pip install . -vv"

        about:
          home: "https://conda.io"
          license: MIT
          license_family: MIT
          summary: "SUMMARY SUMMARY SUMMARY"
          description: "DESCRIPTION DESCRIPTION DESCRIPTION"

        """  # yes, the trailing extra newline is necessary
    )
    assert _print_dict(recipe_metadata, order=recipe_order) == recipe_yaml
