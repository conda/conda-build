"""
Unpack conda packages to streams.
"""

import bz2
import zipfile
import tarfile
import zstandard
import os.path
import json
from contextlib import closing


def tar_generator(fileobj):
    """
    Stream (tarfile, member) from fileobj.
    """
    with closing(tarfile.open(fileobj=fileobj, mode="r|")) as tar:
        for member in tar:
            yield tar, member


def stream_conda_info(filename, fileobj=None):
    """
    Yield members from conda's embedded info/ tarball.

    For .tar.bz2 packages, yield all members.
    """
    if filename.endswith(".conda"):
        # also works with file objects
        zf = zipfile.ZipFile(fileobj or filename)
        info = [info for info in zf.infolist() if info.filename.startswith("info-")]
        assert len(info) == 1
        reader = zstandard.ZstdDecompressor().stream_reader(zf.open(info[0]))
    elif filename.endswith(".tar.bz2"):
        reader = bz2.open(fileobj or filename, mode="rb")
    return tar_generator(reader)


def test():
    import glob

    conda_packages = glob.glob(os.path.expanduser("~/miniconda3/pkgs/*.conda"))
    tarbz_packages = glob.glob(os.path.expanduser("~/miniconda3/pkgs/*.tar.bz2"))

    for packages in (conda_packages, tarbz_packages):
        for package in packages:
            print(package)
            stream = iter(stream_conda_info(package))
            found = False
            for tar, member in stream:
                assert not found, "early exit did not work"
                if member.name == "info/index.json":
                    json.load(tar.extractfile(member))
                    found = True
                    stream.close() # PEP 342 close()
            assert found, f"index.json not found in {package}"


if __name__ == "__main__":
    test()
