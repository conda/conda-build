# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import pytest

from conda_build.license_family import ensure_valid_license_family, guess_license_family

LICENSE_FAMILY = {
    # AGPL
    "Affero GPL": "AGPL",
    # APACHE
    "Apache License (== 2.0)": "APACHE",
    "Apache License 2.0": "APACHE",
    # BSD
    "BSD License": "BSD",
    "BSD_2_clause + file LICENSE": "BSD",
    "BSD_3_clause + file LICENSE": "BSD",
    # CC
    "CC0": "CC",
    # GPL
    "GPL": "GPL",  # previously, GPL3 was incorrectly preferred
    # GPL2
    "GNU General Public License v2 or later (GPLv2+)": "GPL2",
    "GPL-2 | file LICENSE": "GPL2",
    "GPL-2": "GPL2",
    # GPL3
    "GNU General Public License some stuff then a 3 then stuff": "GPL3",
    "GPL (>= 2) | file LICENSE": "GPL3",
    "GPL (>= 2)": "GPL3",
    "GPL (>= 3) | file LICENCE": "GPL3",
    "GPL (>= 3)": "GPL3",
    "GPL 3": "GPL3",
    "GPL-2 | GPL-3 | file LICENSE": "GPL3",  # previously, Public-Domain was incorrectly preferred
    "GPL-2 | GPL-3": "GPL3",
    "GPL-3 | file LICENSE": "GPL3",
    "GPL-3": "GPL3",
    # LGPL
    "BSD License and GNU Library or Lesser General Public License (LGPL)": "LGPL",
    "GNU Lesser General Public License (LGPL)": "LGPL",
    "GNU Lesser General Public License": "LGPL",
    "LGPL (>= 2)": "LGPL",
    "LGPL-2": "LGPL",
    "LGPL-2.1": "LGPL",
    "LGPL-3": "LGPL",
    # MIT
    "MIT + file LICENSE | Unlimited": "MIT",
    "MIT + file LICENSE": "MIT",
    "MIT License": "MIT",
    "Old MIT": "MIT",
    "Unlimited": "MIT",  # unfortunate corner case
    # NONE
    None: "NONE",
    # OTHER
    "BSL-1.0": "OTHER",
    "Custom free software license": "OTHER",
    "file LICENSE (FOSS)": "OTHER",
    "Free software (X11 License)": "OTHER",
    "Lucent Public License": "OTHER",
    "Open Source (http://www.libpng.org/pub/png/src/libpng-LICENSE.txt)": "OTHER",
    "zlib (http://zlib.net/zlib_license.html)": "OTHER",
}


@pytest.mark.parametrize("license,family", LICENSE_FAMILY.items())
def test_guess_license_family(license, family):
    """Test cases where new and deprecated functions match"""
    assert guess_license_family(license) == family


def test_ensure_valid_family(testing_metadata):
    testing_metadata.meta["about"]["license_family"] = "public-domain"
    ensure_valid_license_family(testing_metadata.meta)
    with pytest.raises(RuntimeError):
        testing_metadata.meta["about"]["license_family"] = "local H"
        ensure_valid_license_family(testing_metadata.meta)
