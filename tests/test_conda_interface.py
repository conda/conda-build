# SPDX-FileCopyrightText: © 2012 Continuum Analytics, Inc. <http://continuum.io>
# SPDX-FileCopyrightText: © 2017 Anaconda, Inc. <https://www.anaconda.com>
# SPDX-License-Identifier: BSD-3-Clause
from conda_build import conda_interface as ci


def test_get_installed_version():
    versions = ci.get_installed_version(ci.root_dir, 'conda')
    assert versions.get('conda')
    assert ci.VersionOrder(versions.get('conda'))
