# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os

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
