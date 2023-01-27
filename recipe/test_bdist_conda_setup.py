# SPDX-FileCopyrightText: © 2012 Continuum Analytics, Inc. <http://continuum.io>
# SPDX-FileCopyrightText: © 2017 Anaconda, Inc. <https://www.anaconda.com>
# SPDX-License-Identifier: BSD-3-Clause
from setuptools import setup
import conda_build.bdist_conda

setup(
    name="package",
    version="1.0.0",
    distclass=conda_build.bdist_conda.CondaDistribution,
)
