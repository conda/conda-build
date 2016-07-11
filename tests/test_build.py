"""
This file tests prefix finding for Windows and *nix.
"""

import os
import sys

from conda_build import build

from .utils import testing_workdir

prefix_tests = {"normal": os.path.sep}
if sys.platform == "win32":
    prefix_tests.update({"double_backslash": "\\\\",
                         "forward_slash": "/"})


def _write_prefix(filename, prefix, replacement):
    with open(filename, "w") as f:
        f.write(prefix.replace(os.path.sep, replacement))
        f.write("\n")


def test_find_prefix_files(testing_workdir):
    """
    Write test output that has the prefix to be found, then verify that the prefix finding
    identified the correct number of files.
    """
    # create text files to be replaced
    files = []
    for slash_style in prefix_tests:
        filename = os.path.join(testing_workdir, "%s.txt" % slash_style)
        _write_prefix(filename, testing_workdir, prefix_tests[slash_style])
        files.append(filename)

    assert len(list(build.have_prefix_files(files, testing_workdir))) == len(files)
