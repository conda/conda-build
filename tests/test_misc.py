# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import json
from pathlib import Path

import pytest
from conda.models.enums import PathType

from conda_build._link import pyc_f

try:
    from conda.common.serialize.json import CondaJSONEncoder
except ImportError:
    # FUTURE: remove for `conda>=25.9`
    from conda.auxlib.entity import EntityEncoder as CondaJSONEncoder


@pytest.mark.parametrize(
    "source,python,compiled",
    [
        ("path/utils.py", (2, 7), "path/utils.pyc"),
        ("pa/th/utils.py", (2, 7), "pa/th/utils.pyc"),
        ("path/utils.py", (3, 10), "path/__pycache__/utils.cpython-310.pyc"),
        ("pa/th/utils.py", (3, 10), "pa/th/__pycache__/utils.cpython-310.pyc"),
    ],
)
def test_pyc_f(source, python, compiled):
    assert Path(pyc_f(source, python)) == Path(compiled)


def test_pathtype():
    hardlink = PathType("hardlink")
    assert str(hardlink) == "hardlink"
    assert hardlink.__json__() == "hardlink"

    softlink = PathType("softlink")
    assert str(softlink) == "softlink"
    assert softlink.__json__() == "softlink"


def test_entity_encoder(tmp_path):
    test_file = tmp_path / "test-file"
    test_json = {"a": PathType("hardlink"), "b": 1}
    test_file.write_text(json.dumps(test_json, cls=CondaJSONEncoder))

    json_file = json.loads(test_file.read_text())
    assert json_file == {"a": "hardlink", "b": 1}
