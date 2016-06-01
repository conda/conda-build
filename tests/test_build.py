"""
This file tests prefix finding for Windows and *nix.
"""

import os
import sys

from conda_build import build
from conda.compat import TemporaryDirectory

prefix_tests = {"normal": os.path.sep}
if sys.platform == "win32":
    prefix_tests.update({"double_backslash": "\\\\",
                         "forward_slash": "/"})


def _write_prefix(filename, prefix, replacement):
    with open(filename, "w") as f:
        f.write(prefix.replace(os.path.sep, replacement))
        f.write("\n")


def test_find_prefix_files():
    """
    Write test output that has the prefix to be found, then verify that the prefix finding
    identified the correct number of files.
    """
    # create a temporary folder
    prefix = os.path.join(sys.prefix, "envs", "_build")
    if not os.path.isdir(prefix):
        os.makedirs(prefix)
    with TemporaryDirectory(prefix=prefix + os.path.sep) as tmpdir:
        # create text files to be replaced
        files = []
        for slash_style in prefix_tests:
            filename = os.path.join(tmpdir, "%s.txt" % slash_style)
            _write_prefix(filename, prefix, prefix_tests[slash_style])
            files.append(filename)

        assert len(list(build.have_prefix_files(files))) == len(files)
