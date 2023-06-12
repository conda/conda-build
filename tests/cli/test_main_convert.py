# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os

import pytest

from conda_build.cli import main_convert
from conda_build.conda_interface import download
from conda_build.tarcheck import TarCheck
from conda_build.utils import on_win


@pytest.mark.xfail(
    on_win,
    reason="This is a flaky test that doesn't seem to be working well on Windows.",
)
def test_convert(testing_workdir, testing_config):
    # download a sample py2.7 package
    f = "https://repo.anaconda.com/pkgs/free/win-64/affine-2.0.0-py27_0.tar.bz2"
    pkg_name = "affine-2.0.0-py27_0.tar.bz2"
    download(f, pkg_name)
    # convert it to all platforms
    args = ["-o", "converted", "--platform", "all", pkg_name]
    main_convert.execute(args)
    platforms = ["osx-64", "win-32", "linux-64", "linux-32"]
    for platform in platforms:
        dirname = os.path.join("converted", platform)
        if platform != "win-64":
            assert os.path.isdir(dirname)
            assert pkg_name in os.listdir(dirname)
            testing_config.host_subdir = platform
            with TarCheck(
                os.path.join(dirname, pkg_name), config=testing_config
            ) as tar:
                tar.correct_subdir()
        else:
            assert not os.path.isdir(dirname)
