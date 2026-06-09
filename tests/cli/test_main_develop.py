# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys

import pytest
from conda.gateways.connection.download import download
from pytest import MonkeyPatch

from conda_build.cli import main_develop
from conda_build.utils import get_site_packages, tar_xf


def test_develop(testing_env):
    f = "https://pypi.io/packages/source/c/conda_version_test/conda_version_test-0.1.0-1.tar.gz"
    download(f, "conda_version_test.tar.gz")
    tar_xf("conda_version_test.tar.gz", testing_env)
    extract_folder = "conda_version_test-0.1.0-1"
    cwd = os.getcwd()
    args = ["-p", testing_env, extract_folder]
    # Expect PendingDeprecationWarning since main_develop is deprecated
    with pytest.deprecated_call():
        main_develop.execute(args)
    py_ver = ".".join((str(sys.version_info.major), str(sys.version_info.minor)))
    with open(
        os.path.join(get_site_packages(testing_env, py_ver), "conda.pth")
    ) as f_pth:
        assert cwd in f_pth.read()
    args = ["--uninstall", "-p", testing_env, extract_folder]
    with pytest.deprecated_call():
        main_develop.execute(args)
    with open(
        os.path.join(get_site_packages(testing_env, py_ver), "conda.pth")
    ) as f_pth:
        assert cwd not in f_pth.read()


def test_develop_module_deprecation_warning(monkeypatch: MonkeyPatch):
    """Verify that importing main_develop shows module-level deprecation warning."""
    # delete cached module
    monkeypatch.delitem(
        sys.modules,
        "conda_build.cli.main_develop",
        raising=False,
    )

    with pytest.deprecated_call(
        match=r"conda_build.cli.main_develop is (pending deprecation|deprecated) and will be removed in 27.3",
    ):
        import conda_build.cli.main_develop  # noqa F401


def test_conda_develop_produces_warning(conda_cli):
    """Verify that running `conda develop` produces a deprecation warning."""
    with pytest.deprecated_call():
        conda_cli("develop", "--help", raises=SystemExit)
