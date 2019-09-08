from collections import OrderedDict

from conda_build.skeletons import pypi
from conda_build.skeletons.pypi import _print_dict, _formating_value


def test_version_compare():
    short_version = '2.2'
    long_version = '1.4.5'
    post_version = '2.2.post3'
    pre_version = '2.2.pre3'
    alpha_version = '1.4.5a4'
    beta_version = '1.4.5b4'
    rc_version = '1.4.5rc4'
    padding_version_short = '2.2.0'
    padding_version_long = '1.4.5.0'

    assert pypi.convert_version(short_version) == ' >=2.2,<3'
    assert pypi.convert_version(long_version) == ' >=1.4.5,<1.5'
    assert pypi.convert_version(post_version) == ' >=2.2.post3,<3'
    assert pypi.convert_version(pre_version) == ' >=2.2.pre3,<3'
    assert pypi.convert_version(alpha_version) == ' >=1.4.5a4,<1.5'
    assert pypi.convert_version(beta_version) == ' >=1.4.5b4,<1.5'
    assert pypi.convert_version(rc_version) == ' >=1.4.5rc4,<1.5'
    assert pypi.convert_version(padding_version_short) == ' >=2.2.0,<2.3'
    assert pypi.convert_version(padding_version_long) == ' >=1.4.5.0,<1.4.6'


def test_formating_value():
    assert _formating_value("summary", "SUMMARY SUMMARY") == " \"SUMMARY SUMMARY\"\n"
    assert _formating_value("description", "DESCRIPTION DESCRIPTION") == " \"DESCRIPTION DESCRIPTION\"\n"
    assert _formating_value("script", "SCRIPT VALUE") == " \"SCRIPT VALUE\"\n"
    assert _formating_value("name", "{{name|lower}}") == " \"{{name|lower}}\"\n"
    assert _formating_value("name", "NORMAL NAME") == " NORMAL NAME\n"


def test_print_dict():
    recipe_metadata = {
            "about": OrderedDict(
                [
                    ("home", "https://conda.io"),
                    ("license", "MIT"),
                    ("license_family", "MIT"),
                    ("summary", "SUMMARY SUMMARY SUMMARY"),
                    ("description", "DESCRIPTION DESCRIPTION DESCRIPTION"),
                ]
            ),
            "source": OrderedDict(
                [
                    ("sha256", "4d24b03ffa67638a3fa931c09fd9e0273ffa904e95ebebe7d4b1a54c93d7b732"),
                    ("url", "https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz"),
                ]
            ),
            "package": OrderedDict(
                [("name", "{{ name|lower }}"), ("version", "{{ version }}")]
            ),
            "build": OrderedDict(
                [
                    ("number", 0),
                    ("script", "{{ PYTHON }} -m pip install . -vv"),
                ]
            ),
        }

    assert (
        _print_dict(recipe_metadata, order=["package", "source", "build", "about"])
        == """package:
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

"""
    )
