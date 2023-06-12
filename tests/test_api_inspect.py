# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os

import pytest

from conda_build import api

from .utils import metadata_dir


@pytest.mark.sanity
def test_check_recipe():
    """Technically not inspect, but close enough to belong here"""
    assert api.check(os.path.join(metadata_dir, "source_git_jinja2"))
