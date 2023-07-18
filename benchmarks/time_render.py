# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os

# god-awful hack to get data from the test recipes
import sys

from conda_build import api

_thisdir = os.path.dirname(__file__)
sys.path.append(os.path.dirname(_thisdir))


from tests.utils import metadata_dir  # noqa: E402

variant_dir = os.path.join(metadata_dir, "..", "variants")


def time_simple_render():
    api.render(
        os.path.join(metadata_dir, "python_run"), finalize=False, bypass_env_check=True
    )


def time_top_level_variant_render():
    api.render(
        os.path.join(variant_dir, "02_python_version"),
        finalize=False,
        bypass_env_check=True,
    )


def time_single_top_level_multi_output():
    api.render(
        os.path.join(variant_dir, "test_python_as_subpackage_loop"),
        finalize=False,
        bypass_env_check=True,
    )
