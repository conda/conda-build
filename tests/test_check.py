# SPDX-FileCopyrightText: © 2012 Continuum Analytics, Inc. <http://continuum.io>
# SPDX-FileCopyrightText: © 2017 Anaconda, Inc. <https://www.anaconda.com>
# SPDX-License-Identifier: BSD-3-Clause
import os

from conda_build import api
from .utils import metadata_dir


def test_check_multiple_sources():
    recipe = os.path.join(metadata_dir, 'multiple_sources')
    assert api.check(recipe)
