# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from setuptools import setup

import conda_build.bdist_conda

setup(
    name="package",
    version="1.0.0",
    distclass=conda_build.bdist_conda.CondaDistribution,
)
