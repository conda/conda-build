# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import pytest
from conda import __version__ as conda_version
from conda.core.prefix_data import PrefixData
from packaging.version import Version, parse

from conda_build.inspect_pkg import which_package

if TYPE_CHECKING := False:
    from conda.testing import TmpEnvFixture


@pytest.mark.skipif(
    parse(conda_version) < Version("23.5.0"),
    reason="tmp_env fixture first available in conda 23.5.0",
)
def test_which_package(tmp_env: TmpEnvFixture):
    with tmp_env("ca-certificates") as prefix:
        pd = PrefixData(prefix)
        prec = pd.get("ca-certificates")
        precs = list(which_package(prefix / prec.files[0], prefix))
        assert len(precs) == 1
        assert precs[0] == prec
