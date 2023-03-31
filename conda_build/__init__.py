# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from . import _version

__version__ = _version.get_versions()["version"]


# Sub commands added by conda-build to the conda command
sub_commands = [
    "build",
    "convert",
    "develop",
    "index",
    "inspect",
    "metapackage",
    "render" "skeleton",
]
