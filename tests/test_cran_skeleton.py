# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
Unit tests of the CRAN skeleton utility functions
"""

import os

import pytest
import requests
from conda.auxlib.ish import dals

from conda_build.license_family import allowed_license_families
from conda_build.skeletons.cran import (
    get_cran_archive_versions,
    get_cran_index,
    get_license_info,
    read_description_contents,
    remove_comments,
    sortable_listing_date,
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


# CRAN mirrors serve directory listings in three formats: Apache fancy tables
# (cran.r-project.org), Apache plain pre-formatted text (cloud.r-project.org)
# and nginx autoindex, which also dates entries as "08-Apr-1999 11:06" instead
# of "1999-04-08 11:06". These snippets are modeled on the real listings,
# including the sort-order and parent-directory links the parsers must ignore.
# Matrix appears in both the main and the archive index so that the merge
# keeping its published version is covered.
CRAN_URL = "https://cran.example.org"

FANCY_MAIN_INDEX = """\
<tr><th><a href="?C=N;O=D">Name</a></th><th><a href="?C=M;O=A">Last modified</a></th></tr>
<tr><td><a href="/src/">Parent Directory</a></td><td>&nbsp;</td></tr>
<tr><td><a href="Matrix_1.7-1.tar.gz">Matrix_1.7-1.tar.gz</a></td><td align="right">2024-10-18 09:00  </td></tr>
<tr><td><a href="PACKAGES">PACKAGES</a></td><td align="right">2026-05-06 07:10  </td></tr>
<tr><td><a href="data.table_1.18.4.tar.gz">data.table_1.18.4.tar.gz</a></td><td align="right">2026-05-06 07:10</td></tr>
"""

PLAIN_MAIN_INDEX = """\
<pre>      <a href="?C=N;O=D">Name</a>  <a href="?C=M;O=A">Last modified</a>  <a href="?C=S;O=A">Size</a>  <hr>
      <a href="/src/">Parent Directory</a>                             -
      <a href="Matrix_1.7-1.tar.gz">Matrix_1.7-1.tar.gz</a>            2024-10-18 09:00  2.5M
      <a href="PACKAGES">PACKAGES</a>                                  2026-05-06 05:10  6.5M
      <a href="data.table_1.18.4.tar.gz">data.table_1.18.4.tar.gz</a>  2026-05-06 05:10  5.7M
</pre>
"""

NGINX_MAIN_INDEX = """\
<pre><a href="../">../</a>
<a href="Matrix_1.7-1.tar.gz">Matrix_1.7-1.tar.gz</a>        18-Oct-2024 09:00   2621440
<a href="PACKAGES">PACKAGES</a>                             06-May-2026 05:10   6815744
<a href="data.table_1.18.4.tar.gz">data.table_1.18.4.tar.gz</a>   06-May-2026 05:10   5976883
</pre>
"""

FANCY_ARCHIVE_INDEX = """\
<tr><td><a href="/src/contrib/">Parent Directory</a></td><td>&nbsp;</td></tr>
<tr><td><a href="0test/">0test/</a></td><td align="right">2020-01-01 00:00  </td></tr>
<tr><td><a href="Matrix/">Matrix/</a></td><td align="right">2020-01-01 00:00  </td></tr>
<tr><td><a href="aaSEA/">aaSEA/</a></td><td align="right">2020-01-01 00:00  </td></tr>
<tr><td><a href="rpart/">rpart/</a></td><td align="right">2020-01-01 00:00  </td></tr>
"""

PLAIN_ARCHIVE_INDEX = """\
<pre>      <a href="/src/contrib/">Parent Directory</a>                             -
      <a href="0test/">0test/</a>                  2020-01-01 00:00    -
      <a href="Matrix/">Matrix/</a>                 2020-01-01 00:00    -
      <a href="aaSEA/">aaSEA/</a>                  2020-01-01 00:00    -
      <a href="rpart/">rpart/</a>                  2020-01-01 00:00    -
</pre>
"""

NGINX_ARCHIVE_INDEX = """\
<pre><a href="../">../</a>
<a href="0test/">0test/</a>       01-Jan-2020 00:00    -
<a href="Matrix/">Matrix/</a>     01-Jan-2020 00:00    -
<a href="aaSEA/">aaSEA/</a>       01-Jan-2020 00:00    -
<a href="rpart/">rpart/</a>       01-Jan-2020 00:00    -
</pre>
"""

FANCY_RPART_ARCHIVE = """\
<tr><td><a href="/src/contrib/Archive/">Parent Directory</a></td><td>&nbsp;</td></tr>
<tr><td><a href="PACKAGES.rds">PACKAGES.rds</a></td><td align="right">2026-07-09 04:53  </td></tr>
<tr><td><a href="rpart_1.0-6.tar.gz">rpart_1.0-6.tar.gz</a></td><td align="right">1999-04-08 13:06  </td></tr>
<tr><td><a href="rpart_1.1-1.tar.gz">rpart_1.1-1.tar.gz</a></td><td align="right">2000-01-04 11:47  </td></tr>
<tr><td><a href="rpart_3.1-2.tar.gz">rpart_3.1-2.tar.gz</a></td><td align="right">2001-09-25 09:44  </td></tr>
"""

PLAIN_RPART_ARCHIVE = """\
<pre>      <a href="/src/contrib/Archive/">Parent Directory</a>                             -
      <a href="PACKAGES.rds">PACKAGES.rds</a>            2026-07-09 04:53  3.1K
      <a href="rpart_1.0-6.tar.gz">rpart_1.0-6.tar.gz</a>      1999-04-08 11:06  331K
      <a href="rpart_1.1-1.tar.gz">rpart_1.1-1.tar.gz</a>      2000-01-04 10:47  331K
      <a href="rpart_3.1-2.tar.gz">rpart_3.1-2.tar.gz</a>      2001-09-25 07:44  107K
</pre>
"""

# The nginx dates deliberately do not sort chronologically as plain strings,
# so this also covers the normalization done before sorting.
NGINX_RPART_ARCHIVE = """\
<pre><a href="../">../</a>
<a href="PACKAGES.rds">PACKAGES.rds</a>           09-Jul-2026 04:53   3131
<a href="rpart_1.0-6.tar.gz">rpart_1.0-6.tar.gz</a>   08-Apr-1999 11:06   339173
<a href="rpart_1.1-1.tar.gz">rpart_1.1-1.tar.gz</a>   04-Jan-2000 10:47   338640
<a href="rpart_3.1-2.tar.gz">rpart_3.1-2.tar.gz</a>   25-Sep-2001 07:44   109763
</pre>
"""


def make_response(text="", status_code=200):
    """Build a real requests.Response so error semantics match requests."""
    response = requests.Response()
    response.status_code = status_code
    response.reason = "Gateway Time-out" if status_code >= 400 else "OK"
    response.url = CRAN_URL
    response._content = text.encode()
    return response


class MockSession:
    def __init__(self, responses):
        self.responses = responses

    def get(self, url, **kwargs):
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.parametrize(
    "main_index,archive_index",
    [
        pytest.param(FANCY_MAIN_INDEX, FANCY_ARCHIVE_INDEX, id="fancy"),
        pytest.param(PLAIN_MAIN_INDEX, PLAIN_ARCHIVE_INDEX, id="plain"),
        pytest.param(NGINX_MAIN_INDEX, NGINX_ARCHIVE_INDEX, id="nginx"),
    ],
)
def test_get_cran_index(main_index, archive_index):
    session = MockSession(
        {
            f"{CRAN_URL}/src/contrib/": make_response(main_index),
            f"{CRAN_URL}/src/contrib/Archive/": make_response(archive_index),
        }
    )
    # Matrix is in both listings; the published version must win over the
    # archived entry
    assert get_cran_index(CRAN_URL, session) == {
        "data.table": ("data.table", "1.18.4"),
        "matrix": ("Matrix", "1.7-1"),
        "aasea": ("aaSEA", None),
        "rpart": ("rpart", None),
    }


@pytest.mark.parametrize(
    "archive_failure",
    [
        pytest.param(make_response(status_code=504), id="http-error"),
        pytest.param(requests.exceptions.ReadTimeout("timed out"), id="timeout"),
        pytest.param(
            requests.exceptions.ConnectionError("connection reset"), id="connection"
        ),
    ],
)
@pytest.mark.parametrize(
    "main_index",
    [
        pytest.param(FANCY_MAIN_INDEX, id="fancy"),
        pytest.param(PLAIN_MAIN_INDEX, id="plain"),
    ],
)
def test_get_cran_index_archive_unavailable(main_index, archive_failure, capsys):
    session = MockSession(
        {
            f"{CRAN_URL}/src/contrib/": make_response(main_index),
            f"{CRAN_URL}/src/contrib/Archive/": archive_failure,
        }
    )
    assert get_cran_index(CRAN_URL, session) == {
        "data.table": ("data.table", "1.18.4"),
        "matrix": ("Matrix", "1.7-1"),
    }
    assert "CRAN archive index is unavailable" in capsys.readouterr().out


@pytest.mark.parametrize(
    "archive_listing",
    [
        pytest.param(FANCY_RPART_ARCHIVE, id="fancy"),
        pytest.param(PLAIN_RPART_ARCHIVE, id="plain"),
        pytest.param(NGINX_RPART_ARCHIVE, id="nginx"),
    ],
)
def test_get_cran_archive_versions(archive_listing):
    session = MockSession(
        {f"{CRAN_URL}/src/contrib/Archive/rpart/": make_response(archive_listing)}
    )
    # sorted by archival date, newest first
    assert get_cran_archive_versions(CRAN_URL, session, "rpart") == [
        "3.1-2",
        "1.1-1",
        "1.0-6",
    ]


def test_get_cran_archive_versions_missing():
    session = MockSession(
        {
            f"{CRAN_URL}/src/contrib/Archive/no.such.package/": make_response(
                status_code=404
            )
        }
    )
    assert get_cran_archive_versions(CRAN_URL, session, "no.such.package") == []


@pytest.mark.parametrize(
    "date,expected",
    [
        pytest.param("1999-04-08 11:06", "1999-04-08 11:06", id="apache"),
        pytest.param("08-Apr-1999 11:06", "1999-04-08 11:06", id="nginx"),
        pytest.param("not a date", "not a date", id="unrecognized"),
    ],
)
def test_sortable_listing_date(date, expected):
    assert sortable_listing_date(date) == expected
