# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
# for tests only
def _patch_repodata(repodata, subdir):
    instructions = {
        "patch_instructions_version": 1,
        "packages": {},
        "revoke": [],
        "remove": [],
    }
    return instructions
