# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys

from conda.core.prefix_data import PrefixData

from conda_build import environ


def test_environment_creation_preserves_PATH(testing_workdir, testing_config):
    ref_path = os.environ["PATH"]
    environ.create_env(
        testing_workdir,
        ["python"],
        env="host",
        config=testing_config,
        subdir=testing_config.build_subdir,
    )
    assert os.environ["PATH"] == ref_path


def test_environment():
    """Asserting PrefixData can accomplish the same thing as Environment."""
    assert (specs := environ.Environment(sys.prefix).package_specs())
    assert specs == [
        f"{prec.name} {prec.version} {prec.build}"
        for prec in PrefixData(sys.prefix).iter_records()
    ]
