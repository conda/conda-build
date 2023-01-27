# SPDX-FileCopyrightText: © 2012 Continuum Analytics, Inc. <http://continuum.io>
# SPDX-FileCopyrightText: © 2017 Anaconda, Inc. <https://www.anaconda.com>
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
