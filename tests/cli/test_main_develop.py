# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from conda.gateways.connection.download import download

from conda_build.cli import main_develop
from conda_build.utils import get_site_packages, tar_xf

if TYPE_CHECKING:
    from conda.testing import TmpEnvFixture


def test_develop(tmp_env: TmpEnvFixture) -> None:
    py_ver = "%d.%d" % sys.version_info[:2]
    with tmp_env(f"python={py_ver}") as prefix:
        download(
            "https://pypi.io/packages/source/c/conda_version_test/conda_version_test-0.1.0-1.tar.gz",
            "conda_version_test.tar.gz",
        )
        tar_xf("conda_version_test.tar.gz", prefix)
        extract_folder = "conda_version_test-0.1.0-1"

        main_develop.execute([f"--prefix={prefix}", extract_folder])
        assert (
            str(Path.cwd())
            in Path(get_site_packages(prefix, py_ver), "conda.pth").read_text()
        )

        main_develop.execute(["--uninstall", f"--prefix={prefix}", extract_folder])
        assert (
            str(Path.cwd())
            not in Path(get_site_packages(prefix, py_ver), "conda.pth").read_text()
        )
