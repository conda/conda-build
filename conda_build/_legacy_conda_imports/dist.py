# Copyright (C) 2012 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""(Legacy) Low-level implementation of a Channel."""
import re

from conda.base.constants import CONDA_PACKAGE_EXTENSIONS


def dist_string_from_package_record(package_record):
    string = package_record.fn

    if string.endswith("@"):
        raise NotImplementedError()

    REGEX_STR = (
        r"(?:([^\s\[\]]+)::)?"  # optional channel
        r"([^\s\[\]]+)"  # 3.x dist
        r"(?:\[([a-zA-Z0-9_-]+)\])?"  # with_features_depends
    )
    channel, original_dist, w_f_d = re.search(REGEX_STR, string).groups()

    stripped = original_dist
    for ext in CONDA_PACKAGE_EXTENSIONS:
        if stripped.endswith(ext):
            stripped = stripped[: -len(ext)]
    return stripped
