# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import re
import string

from conda_build import exceptions
from conda_build.utils import comma_join

allowed_license_families = """
AGPL
LGPL
GPL3
GPL2
GPL
BSD
MIT
APACHE
PSF
CC
MOZILLA
PUBLIC-DOMAIN
PROPRIETARY
OTHER
NONE
""".split()

# regular expressions
gpl2_regex = re.compile("GPL[^3]*2")  # match GPL2
gpl3_regex = re.compile("GPL[^2]*3")  # match GPL3
gpl23_regex = re.compile("GPL[^2]*>= *2")  # match GPL >= 2
cc_regex = re.compile(r"CC\w+")  # match CC
punk_regex = re.compile("[%s]" % re.escape(string.punctuation))  # removes punks


def match_gpl3(family):
    """True if family matches GPL3 or GPL >= 2, else False"""
    return gpl23_regex.search(family) or gpl3_regex.search(family)


def normalize(s):
    """Set to ALL CAPS, replace common GPL patterns, and strip"""
    s = s.upper()
    s = re.sub("GENERAL PUBLIC LICENSE", "GPL", s)
    s = re.sub("LESSER *", "L", s)
    s = re.sub("AFFERO *", "A", s)
    return s.strip()


def remove_special_characters(s):
    """Remove punctuation, spaces, tabs, and line feeds"""
    s = punk_regex.sub(" ", s)
    s = re.sub(r"\s+", "", s)
    return s


def guess_license_family_from_index(index=None, recognized=allowed_license_families):
    """Return best guess of license_family from the conda package index.

    Note: Logic here is simple, and focuses on existing set of allowed families
    """

    if isinstance(index, dict):
        license_name = index.get("license_family", index.get("license"))
    else:  # index argument is actually a string
        license_name = index

    return guess_license_family(license_name, recognized)


def guess_license_family(license_name=None, recognized=allowed_license_families):
    """Return best guess of license_family from the conda package index.

    Note: Logic here is simple, and focuses on existing set of allowed families
    """

    if license_name is None:
        return "NONE"

    license_name = normalize(license_name)

    # Handle GPL families as special cases
    # Remove AGPL and LGPL before looking for GPL2 and GPL3
    sans_lgpl = re.sub("[A,L]GPL", "", license_name)
    if match_gpl3(sans_lgpl):
        return "GPL3"
    elif gpl2_regex.search(sans_lgpl):
        return "GPL2"
    elif cc_regex.search(license_name):
        return "CC"

    license_name = remove_special_characters(license_name)
    for family in recognized:
        if remove_special_characters(family) in license_name:
            return family
    for family in recognized:
        if license_name in remove_special_characters(family):
            return family
    return "OTHER"


def ensure_valid_license_family(meta):
    try:
        license_family = meta["about"]["license_family"]
    except KeyError:
        return
    allowed_families = [
        remove_special_characters(normalize(fam)) for fam in allowed_license_families
    ]
    if remove_special_characters(normalize(license_family)) not in allowed_families:
        raise RuntimeError(
            exceptions.indent(
                "about/license_family '%s' not allowed. Allowed families are %s."
                % (license_family, comma_join(sorted(allowed_license_families)))
            )
        )
