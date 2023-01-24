# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os.path

from conda_build.cli import main_index


def testing_index(testing_workdir):
    args = ["."]
    main_index.execute(args)
    assert os.path.isfile("noarch/repodata.json")
