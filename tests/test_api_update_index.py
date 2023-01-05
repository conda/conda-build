# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from pathlib import Path

from conda_build.api import update_index


def test_update_index(testing_workdir):
    update_index(testing_workdir)

    for name in ("repodata.json", "repodata.json.bz2"):
        assert Path(testing_workdir, "noarch", name).is_file()
