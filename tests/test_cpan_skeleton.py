# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
Unit tests of the CPAN skeleton utility functions
"""


from pathlib import Path

import pytest

from conda_build.skeletons.cpan import get_core_modules_for_this_perl_version
from conda_build.variants import get_default_variant


@pytest.mark.slow
def test_core_modules(testing_config):
    """
    Check expected core modules are recognized
    (excluding known removed ones, e.g., Module::Build)
    """
    cache_dir = Path(testing_config.src_cache_root, ".conda-build", "pickled.cb")
    perl_version = testing_config.variant.get(
        "perl", get_default_variant(testing_config)["perl"]
    )
    core_modules = get_core_modules_for_this_perl_version(perl_version, str(cache_dir))
    assert "Config" in core_modules
    assert "Module::Build" not in core_modules
