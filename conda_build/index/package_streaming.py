"""
Unpack conda packages to streams.
"""

import bz2
import zipfile
import tarfile
import zstandard
import os.path
import json


def tar_generator(fileobj):
    """
    Stream url, stop when all files in set checklist (file names like
    info/recipe/meta.yaml) have been found.
    """
    tar = tarfile.open(fileobj=fileobj, mode="r|")
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
    return tar_generator(reader)  # XXX facilitate explicit closing


def test():
    import glob

    conda_packages = glob.glob(os.path.expanduser("~/miniconda3/pkgs/*.conda"))
    tarbz_packages = glob.glob(os.path.expanduser("~/miniconda3/pkgs/*.tar.bz2"))

    for package in conda_packages:
        print(package)
        for tar, member in stream_conda_info(package):
            if member.name == "info/index.json":
                json.load(tar.extractfile(member))
                break
        else:
            assert False, "index.json not found"

    for package in tarbz_packages:
        print(package)
        for tar, member in stream_conda_info(package):
            if member.name == "info/index.json":
                json.load(tar.extractfile(member))
                break
        else:
            assert False, "index.json not found"

if __name__ == "__main__":
    test()
