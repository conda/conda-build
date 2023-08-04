# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conda_build import jinja_context
from conda_build.utils import HashableDict


def test_pin_default(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, "get_env_dependencies")
    get_env_dependencies.return_value = ["test 1.2.3"], [], None
    pin = jinja_context.pin_compatible(testing_metadata, "test")
    assert pin == "test >=1.2.3,<2.0a0"


def test_pin_compatible_exact(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, "get_env_dependencies")
    get_env_dependencies.return_value = ["test 1.2.3 abc_0"], [], None
    pin = jinja_context.pin_compatible(testing_metadata, "test", exact=True)
    assert pin == "test 1.2.3 abc_0"


def test_pin_jpeg_style_default(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, "get_env_dependencies")
    get_env_dependencies.return_value = ["jpeg 9d 0"], [], None
    pin = jinja_context.pin_compatible(testing_metadata, "jpeg")
    assert pin == "jpeg >=9d,<10a"


def test_pin_jpeg_style_minor(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, "get_env_dependencies")
    get_env_dependencies.return_value = ["jpeg 9d 0"], [], None
    pin = jinja_context.pin_compatible(testing_metadata, "jpeg", max_pin="x.x")
    assert pin == "jpeg >=9d,<9e"


def test_pin_openssl_style_bugfix(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, "get_env_dependencies")
    get_env_dependencies.return_value = ["openssl 1.0.2j 0"], [], None
    pin = jinja_context.pin_compatible(testing_metadata, "openssl", max_pin="x.x.x")
    assert pin == "openssl >=1.0.2j,<1.0.3a"
    pin = jinja_context.pin_compatible(testing_metadata, "openssl", max_pin="x.x.x.x")
    assert pin == "openssl >=1.0.2j,<1.0.2k"


def test_pin_major_minor(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, "get_env_dependencies")
    get_env_dependencies.return_value = ["test 1.2.3"], [], None
    pin = jinja_context.pin_compatible(testing_metadata, "test", max_pin="x.x")
    assert pin == "test >=1.2.3,<1.3.0a0"


def test_pin_excessive_max_pin(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, "get_env_dependencies")
    get_env_dependencies.return_value = ["test 1.2.3"], [], None
    pin = jinja_context.pin_compatible(testing_metadata, "test", max_pin="x.x.x.x.x.x")
    assert pin == "test >=1.2.3,<1.2.4.0a0"


def test_pin_upper_bound(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, "get_env_dependencies")
    get_env_dependencies.return_value = ["test 1.2.3"], [], None
    pin = jinja_context.pin_compatible(testing_metadata, "test", upper_bound="3.0")
    assert pin == "test >=1.2.3,<3.0"


def test_pin_lower_bound(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, "get_env_dependencies")
    get_env_dependencies.return_value = ["test 1.2.3"], [], None
    pin = jinja_context.pin_compatible(testing_metadata, "test", lower_bound=1.0)
    assert pin == "test >=1.0,<2.0a0"


def test_pin_none_min(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, "get_env_dependencies")
    get_env_dependencies.return_value = ["test 1.2.3"], [], None
    pin = jinja_context.pin_compatible(testing_metadata, "test", min_pin=None)
    assert pin == "test <2.0a0"


def test_pin_none_max(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, "get_env_dependencies")
    get_env_dependencies.return_value = ["test 1.2.3"], [], None
    pin = jinja_context.pin_compatible(testing_metadata, "test", max_pin=None)
    assert pin == "test >=1.2.3"


def test_pin_subpackage_exact(testing_metadata):
    name = testing_metadata.name()
    output_dict = {"name": name}
    testing_metadata.meta["outputs"] = [output_dict]
    fm = testing_metadata.get_output_metadata(output_dict)
    testing_metadata.other_outputs = {
        (name, HashableDict(testing_metadata.config.variant)): (output_dict, fm)
    }
    pin = jinja_context.pin_subpackage(testing_metadata, name, exact=True)
    assert len(pin.split()) == 3


def test_pin_subpackage_expression(testing_metadata):
    name = testing_metadata.name()
    output_dict = {"name": name}
    testing_metadata.meta["outputs"] = [output_dict]
    fm = testing_metadata.get_output_metadata(output_dict)
    testing_metadata.other_outputs = {
        (name, HashableDict(testing_metadata.config.variant)): (output_dict, fm)
    }
    pin = jinja_context.pin_subpackage(testing_metadata, name)
    assert len(pin.split()) == 2


def test_resolved_packages(testing_metadata):
    testing_metadata.meta["requirements"]["build"] = ["numpy"]
    packages = jinja_context.resolved_packages(testing_metadata, "build")
    assert all(len(pkg.split()) == 3 for pkg in packages)
    assert any("numpy" == pkg.split()[0] for pkg in packages)
    assert any("python" == pkg.split()[0] for pkg in packages)


def test_load_setup_py_data_from_setup_cfg(testing_metadata, tmp_path: Path):
    setup_py = tmp_path / "setup.py"
    setup_cfg = tmp_path / "setup.cfg"
    setup_py.write_text(
        "from setuptools import setup\n" 'setup(name="name_from_setup_py")\n'
    )
    setup_cfg.write_text(
        "[metadata]\n"
        "name = name_from_setup_cfg\n"
        "version = version_from_setup_cfg\n"
        "[options.extras_require]\n"
        "extra = extra_package\n"
    )
    setuptools_data = jinja_context.load_setup_py_data(testing_metadata, str(setup_py))
    # ensure that setup.cfg has priority over setup.py
    assert setuptools_data["name"] == "name_from_setup_cfg"
    assert setuptools_data["version"] == "version_from_setup_cfg"
    assert setuptools_data["extras_require"] == {"extra": ["extra_package"]}


@pytest.mark.parametrize(
    "filename,fmt,data,expected",
    [
        ("file.json", None, '{"a": 1}', {"a": 1}),
        ("json_file", "json", '{"a": 1}', {"a": 1}),
        ("file.toml", None, "[tbl]\na = 1", {"tbl": {"a": 1}}),
        ("toml_file", "toml", "[tbl]\na = 1", {"tbl": {"a": 1}}),
        ("file.yaml", None, "a: 1\nb:\n  - c: 2", {"a": 1, "b": [{"c": 2}]}),
    ],
)
def test_load_file_data(
    tmp_path: Path,
    filename: str,
    fmt: str | None,
    data: str,
    expected: Any,
    testing_metadata,
):
    path = tmp_path / filename
    path.write_text(data)
    assert (
        jinja_context.load_file_data(str(path), fmt, config=testing_metadata.config)
        == expected
    )
