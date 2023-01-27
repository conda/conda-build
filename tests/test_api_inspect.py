# SPDX-FileCopyrightText: © 2012 Continuum Analytics, Inc. <http://continuum.io>
# SPDX-FileCopyrightText: © 2017 Anaconda, Inc. <https://www.anaconda.com>
# SPDX-License-Identifier: BSD-3-Clause
import os

import pytest

from conda_build import api
from .utils import metadata_dir


@pytest.mark.sanity
def test_check_recipe():
    """Technically not inspect, but close enough to belong here"""
    assert api.check(os.path.join(metadata_dir, "source_git_jinja2"))
