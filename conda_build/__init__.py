# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from .__version__ import __version__

__all__ = ["__version__"]

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
