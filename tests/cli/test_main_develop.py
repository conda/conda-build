# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys

from conda_build.cli import main_develop
from conda_build.conda_interface import download
from conda_build.utils import get_site_packages, tar_xf


def test_develop(testing_env):
    f = "https://pypi.io/packages/source/c/conda_version_test/conda_version_test-0.1.0-1.tar.gz"
    download(f, "conda_version_test.tar.gz")
    tar_xf("conda_version_test.tar.gz", testing_env)
    extract_folder = "conda_version_test-0.1.0-1"
    cwd = os.getcwd()
    args = ["-p", testing_env, extract_folder]
    main_develop.execute(args)
    py_ver = ".".join((str(sys.version_info.major), str(sys.version_info.minor)))
    with open(
        os.path.join(get_site_packages(testing_env, py_ver), "conda.pth")
    ) as f_pth:
        assert cwd in f_pth.read()
    args = ["--uninstall", "-p", testing_env, extract_folder]
    main_develop.execute(args)
    with open(
        os.path.join(get_site_packages(testing_env, py_ver), "conda.pth")
    ) as f_pth:
        assert cwd not in f_pth.read()
