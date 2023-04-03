# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
Unit tests of the CRAN skeleton utility functions
"""
import os

import pytest
from conda.auxlib.ish import dals

from conda_build.license_family import allowed_license_families
from conda_build.skeletons.cran import (
    get_license_info,
    read_description_contents,
    remove_comments,
)

from .utils import cran_dir


@pytest.mark.parametrize(
    "license_string, license_id, license_family, license_files",
    [
        pytest.param(
            "GPL-3",
            "GPL-3",
            "GPL3",
            dals(
                """
                license_file:
                    - '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3'
                """
            ),
            id="GPL-3",
        ),
        pytest.param(
            "Artistic License 2.0",
            "Artistic-2.0",
            "OTHER",
            dals(
                """
                license_file:
                    - '{{ environ["PREFIX"] }}/lib/R/share/licenses/Artistic-2.0'
                """
            ),
            id="Artistic-2.0",
        ),
        pytest.param("MPL-2.0", "MPL-2.0", "OTHER", "", id="MPL-2.0"),
        pytest.param(
            "MIT + file LICENSE",
            "MIT",
            "MIT",
            dals(
                """
                license_file:
                    - '{{ environ["PREFIX"] }}/lib/R/share/licenses/MIT'
                    - LICENSE
                """
            ),
            id="MIT",
        ),
        pytest.param(
            "BSD 2-clause License + file LICENSE",
            "BSD_2_clause",
            "BSD",
            dals(
                """
                license_file:
                    - '{{ environ["PREFIX"] }}/lib/R/share/licenses/BSD_2_clause'
                    - LICENSE
                """
            ),
            id="BSD_2_clause",
        ),
        pytest.param(
            "GPL-2 | GPL-3",
            "GPL-2 | GPL-3",
            "GPL3",
            dals(
                """
                license_file:
                    - '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-2'
                    - '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3'
                """
            ),
            id="GPL-2 | GPL-3",
        ),
        pytest.param(
            "GPL-3 | GPL-2",
            "GPL-3 | GPL-2",
            "GPL3",
            dals(
                """
                license_file:
                    - '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3'
                    - '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-2'
                """
            ),
            id="GPL-3 | GPL-2",
        ),
        pytest.param(
            "GPL (>= 2)",
            "GPL-2",
            "GPL2",
            dals(
                """
                license_file:
                    - '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-2'
                """
            ),
            id="GPL-2",
        ),
    ],
)
def test_get_license_info(license_string, license_id, license_family, license_files):
    observed = get_license_info(license_string, allowed_license_families)
    assert observed[0] == license_id
    assert observed[2] == license_family
    assert observed[1] == license_files


def test_read_description_contents():
    description = os.path.join(cran_dir, "rpart", "DESCRIPTION")
    with open(description, "rb") as fp:
        contents = read_description_contents(fp)
    assert contents["Package"] == "rpart"
    assert contents["Priority"] == "recommended"
    assert contents["Title"] == "Recursive Partitioning and Regression Trees"
    assert contents["Depends"] == "R (>= 2.15.0), graphics, stats, grDevices"
    assert contents["License"] == "GPL-2 | GPL-3"
    assert (
        contents["URL"]
        == "https://github.com/bethatkinson/rpart, https://cran.r-project.org/package=rpart"
    )


def test_remove_comments():
    with_comments = dals(
        """
        #!keep
        # remove
          # remove
        keep
        keep # keep
        """
    )
    without_comments = dals(
        """
        #!keep
        keep
        keep # keep
        """
    )
    assert remove_comments(with_comments) == without_comments
