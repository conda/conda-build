# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
Simple tests for testing functions in develop module - lower level than going through API.
"""
from pathlib import Path
from typing import Generator

import pytest

from conda_build.develop import _uninstall, write_to_conda_pth
from conda_build.utils import rm_rf

from .utils import thisdir


@pytest.fixture(scope="session")
def site_packages() -> Generator[Path, None, None]:
    """
    create site-packges/ directory in same place where test is located. This
    is where tests look conda.pth file. It is a session scoped fixture and
    it has a finalizer function invoked in the end to remove site-packages/
    directory
    """
    site_packages = Path(thisdir, "site-packages")
    if site_packages.exists():
        rm_rf(str(site_packages))

    site_packages.mkdir(exist_ok=True)

    yield site_packages

    rm_rf(str(site_packages))


@pytest.fixture(scope="function")
def conda_pth(site_packages: Path) -> Generator[Path, None, None]:
    """
    Returns the path to conda.pth - though we don't expect name to change
    from conda.pth, better to keep this in one place

    Removes 'conda.pth' if it exists so each test starts without a conda.pth
    file
    """
    path = site_packages / "conda.pth"
    if path.exists():
        path.unlink()

    yield path

    if path.exists():
        path.unlink()


DEVELOP_PATHS = ("/path/to/one", "/path/to/two", "/path/to/three")


def test_write_to_conda_pth(site_packages: Path, conda_pth: Path):
    """
    `conda develop pkg_path` invokes write_to_conda_pth() to write/append to
    conda.pth
    """
    assert not conda_pth.exists()

    for count, path in enumerate(DEVELOP_PATHS, start=1):
        # adding path
        write_to_conda_pth(site_packages, path)
        assert conda_pth.exists()

        develop_paths = list(filter(None, conda_pth.read_text().split("\n")))
        assert path in develop_paths
        assert len(develop_paths) == count

        # adding path a second time has no effect
        write_to_conda_pth(site_packages, path)

        assert list(filter(None, conda_pth.read_text().split("\n"))) == develop_paths


def test_uninstall(site_packages: Path, conda_pth: Path):
    """
    `conda develop --uninstall pkg_path` invokes uninstall() to remove path
    from conda.pth
    """
    for path in DEVELOP_PATHS:
        write_to_conda_pth(site_packages, path)

    for count, path in enumerate(DEVELOP_PATHS, start=1):
        # removing path
        _uninstall(site_packages, path)
        assert conda_pth.exists()

        develop_paths = list(filter(None, conda_pth.read_text().split("\n")))
        assert path not in develop_paths
        assert len(develop_paths) == len(DEVELOP_PATHS) - count

        # removing path a second time has no effect
        _uninstall(site_packages, path)

        assert list(filter(None, conda_pth.read_text().split("\n"))) == develop_paths
