# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
Integrative tests of the CPAN skeleton that start from
conda_build.api.skeletonize and check the output files
"""


import pytest

from conda_build import api
from conda_build.jinja_context import compiler


@pytest.mark.slow
@pytest.mark.flaky(rerun=5, reruns_delay=2)
def test_xs_needs_c_compiler(testing_config):
    """Perl packages with XS files need a C compiler"""
    # This uses Sub::Identify=0.14 since it includes no .c files but a .xs file.
    api.skeletonize("Sub::Identify", version="0.14", repo="cpan", config=testing_config)
    m = api.render("perl-sub-identify/0.14", finalize=False, bypass_env_check=True)[0][
        0
    ]
    build_requirements = m.get_value("requirements/build")
    assert compiler("c", testing_config) in build_requirements
