# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys

env_vars = [
    "FEATURE_DEBUG",
    "FEATURE_NOMKL",
    "FEATURE_OPT",
]

# list of features, where each element is a tuple(name, boolean), i.e. having
# FEATURE_DEBUG=1 and FEATURE_NOMKL=0 -> [('debug', True), ('nomkl', False)]
feature_list = []
for key, value in os.environ.items():
    if key in env_vars:
        if value not in ("0", "1"):
            sys.exit(
                f"Error: did not expect environment variable '{key}' "
                f"being set to '{value}' (not '0' or '1')"
            )
        feature_list.append((key[8:].lower(), bool(int(value))))
