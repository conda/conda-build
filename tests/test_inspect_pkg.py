# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from conda.core.prefix_data import PrefixData
from conda.testing import TmpEnvFixture

from conda_build.inspect_pkg import which_package


def test_which_package(tmp_env: TmpEnvFixture):
    with tmp_env("ca-certificates") as prefix:
        pd = PrefixData(prefix)
        prec = pd.get("ca-certificates")
        precs = list(which_package(prefix / prec.files[0], prefix))
        assert len(precs) == 1
        assert precs[0] == prec
