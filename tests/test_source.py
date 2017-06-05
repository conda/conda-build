"""
This file tests the source.py module.  It sits lower in the stack than the API tests,
and is more unit-test oriented.
"""

import os
import tarfile

from conda_build.source import download_to_cache
from conda_build.conda_interface import TemporaryDirectory


def test_source_user_expand(testing_workdir):
    with TemporaryDirectory(dir=os.path.expanduser('~')) as tmp:
        with TemporaryDirectory() as tbz_srcdir:
            file_txt = os.path.join(tbz_srcdir, "file.txt")
            with open(file_txt, 'w') as f:
                f.write("hello")
            tbz_name = os.path.join(tmp, "cb-test.tar.bz2")
            with tarfile.open(tbz_name, "w:bz2") as tar:
                tar.add(tbz_srcdir, arcname=os.path.sep)
            for prefix in ('~', 'file://~'):
                source_dict = {"url": os.path.join(prefix, os.path.basename(tmp), "cb-test.tar.bz2")}
                with TemporaryDirectory() as tmp2:
                    download_to_cache(tmp2, '', source_dict)
