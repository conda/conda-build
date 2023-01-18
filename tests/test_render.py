# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os

import pytest

from conda_build import api
from conda_build import render


@pytest.mark.parametrize(
    "build",
    [
        pytest.param({"noarch": "python"}, id="noarch"),
        pytest.param({"noarch_python": True}, id="noarch_python"),
    ],
)
def test_noarch_output(build, testing_metadata):
    testing_metadata.meta["build"].update(build)
    output = api.get_output_file_path(testing_metadata)
    assert os.path.sep + "noarch" + os.path.sep in output[0]


def test_reduce_duplicate_specs(testing_metadata):
    testing_metadata.meta["requirements"] = {
        "build": ["exact", "exact 1.2.3 1", "exact >1.0,<2"],
        "host": ["exact", "exact 1.2.3 1"],
    }
    render._simplify_to_exact_constraints(testing_metadata)
    simplified = testing_metadata.meta["requirements"]

    assert simplified["build"] == simplified["host"]
    assert len(simplified["build"]) == 1
    assert "exact 1.2.3 1" in simplified["build"]


def test_pin_run_as_build_preserve_string(testing_metadata):
    m = testing_metadata
    m.config.variant['pin_run_as_build']['pkg'] = {
        'max_pin': 'x.x'
    }
    dep = render.get_pin_from_build(
        m,
        'pkg * somestring*',
        {'pkg': '1.2.3 somestring_h1234'}
    )
    assert dep == 'pkg >=1.2.3,<1.3.0a0 somestring*'
