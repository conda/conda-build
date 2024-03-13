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
    "render",
    "skeleton",
]

# Skip context logic for docs since we don't install all dependencies
try:
    import os

    from conda.base.context import reset_context

    # Disallow softlinks. This avoids a lot of dumb issues, at the potential cost of disk space.
    os.environ["CONDA_ALLOW_SOFTLINKS"] = "false"
    reset_context()

except ImportError:
    pass
