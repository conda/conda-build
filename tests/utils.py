# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import contextlib
from glob import glob
import os
from pathlib import Path
import shlex
import sys
from typing import Generator

import pytest
from conda.common.compat import on_mac, on_win
from conda_build.metadata import MetaData
from conda_build.conda_interface import linked


def numpy_installed():
    return any([True for dist in linked(sys.prefix) if dist.name == "numpy"])


tests_path = Path(__file__).parent
metadata_path = tests_path / "test-recipes" / "metadata"
subpackage_path = tests_path / "test-recipes" / "split-packages"
fail_path = tests_path / "test-recipes" / "fail"
variants_path = tests_path / "test-recipes" / "variants"
dll_path = tests_path / "test-recipes" / "dll-package"
go_path = tests_path / "test-recipes" / "go-package"
published_path = tests_path / "test-recipes" / "published_code"
archive_path = tests_path / "archives"
cran_path = tests_path / "test-cran-skeleton"

# backport
thisdir = str(tests_path)
metadata_dir = str(metadata_path)
subpackage_dir = str(subpackage_path)
fail_dir = str(fail_path)
variants_dir = str(variants_path)
dll_dir = str(dll_path)
go_dir = str(go_path)
published_dir = str(published_path)
archive_dir = str(archive_path)
cran_dir = str(cran_path)

#Moved From test_api_debug.py file
recipe_path = os.path.join(metadata_dir, "_debug_pkg")
ambiguous_recipe_path = os.path.join(metadata_dir, "_debug_pkg_multiple_outputs")
tarball_path = os.path.join(thisdir, "archives", "test_debug_pkg-1.0-0.tar.bz2")

SHELL_CMD = ("cmd.exe", "/d", "/c") if on_win else ("bash", "-c")


def assert_correct_folders(work_dir, build=True):
    base_dir = os.path.dirname(work_dir)
    build_set = "_b*", "_h*"
    test_set = "_t*", "test_tmp"
    for prefix in build_set:
        assert bool(glob(os.path.join(base_dir, prefix))) == build
    for prefix in test_set:
        assert bool(glob(os.path.join(base_dir, prefix))) != build


def check_build_files_present(work_dir, build=True):
    if on_win:
        assert os.path.exists(os.path.join(work_dir, "bld.bat")) == build
    else:
        assert os.path.exists(os.path.join(work_dir, "conda_build.sh")) == build


def check_test_files_present(work_dir, test=True):
    if on_win:
        assert os.path.exists(os.path.join(work_dir, "conda_test_runner.bat")) == test
    else:
        assert os.path.exists(os.path.join(work_dir, "conda_test_runner.sh")) == test


def is_valid_dir(*parts: Path | str) -> bool:
    path = Path(*parts)
    return (
        # only directories are valid recipes
        path.is_dir()
        # recipes prefixed with _ are special and shouldn't be run as part of bulk tests
        and not path.name.startswith("_")
        # exclude macOS-only recipes
        and (path.name not in ["osx_is_app"] or on_mac)
    )


def get_valid_recipes(*parts: Path | str) -> Generator[Path, None, None]:
    yield from filter(is_valid_dir, Path(*parts).iterdir())


def add_mangling(filename):
    filename = os.path.splitext(filename)[0] + ".cpython-{}{}.py".format(
        sys.version_info.major, sys.version_info.minor
    )
    filename = os.path.join(
        os.path.dirname(filename), "__pycache__", os.path.basename(filename)
    )
    return filename + "c"


def assert_package_consistency(package_path):
    """Assert internal consistency of package

    - All files in info/files are included in package
    - All files in info/has_prefix is included in info/files
    - All info in paths.json is correct (not implemented - currently fails for conda-convert)

    Return nothing, but raise RuntimeError if inconsistencies are found.
    """
    import tarfile

    try:
        with tarfile.open(package_path) as t:
            # Read info from tar file
            member_list = t.getnames()
            files = t.extractfile("info/files").read().decode("utf-8")
            # Read info/has_prefix if present
            if "info/has_prefix" in member_list:
                has_prefix_present = True
                has_prefix = t.extractfile("info/has_prefix").read().decode("utf-8")
            else:
                has_prefix_present = False
    except tarfile.ReadError:
        raise RuntimeError(
            "Could not extract metadata from %s. "
            "File probably corrupt." % package_path
        )
    errors = []
    member_set = set(member_list)  # The tar format allows duplicates in member_list
    # Read info from info/files
    file_list = files.splitlines()
    file_set = set(file_list)
    # Check that there are no duplicates in info/files
    if len(file_list) != len(file_set):
        errors.append("Duplicate files in info/files in %s" % package_path)
    # Compare the contents of files and members
    unlisted_members = member_set.difference(file_set)
    missing_members = file_set.difference(member_set)
    # Find any unlisted members outside the info directory
    missing_files = [m for m in unlisted_members if not m.startswith("info/")]
    if len(missing_files) > 0:
        errors.append(
            "The following package files are not listed in "
            "info/files: %s" % ", ".join(missing_files)
        )
    # Find any files missing in the archive
    if len(missing_members) > 0:
        errors.append(
            "The following files listed in info/files are missing: "
            "%s" % ", ".join(missing_members)
        )
    # Find any files in has_prefix that are not present in files
    if has_prefix_present:
        prefix_path_list = []
        for line in has_prefix.splitlines():
            # (parsing from conda/gateways/disk/read.py::read_has_prefix() in conda repo)
            parts = tuple(x.strip("\"'") for x in shlex.split(line, posix=False))
            if len(parts) == 1:
                prefix_path_list.append(parts[0])
            elif len(parts) == 3:
                prefix_path_list.append(parts[2])
            else:
                errors.append("Invalid has_prefix file in package: %s" % package_path)
        prefix_path_set = set(prefix_path_list)
        if len(prefix_path_list) != len(prefix_path_set):
            errors.append("Duplicate files in info/has_prefix in %s" % package_path)
        prefix_not_in_files = prefix_path_set.difference(file_set)
        if len(prefix_not_in_files) > 0:
            errors.append(
                "The following files listed in info/has_prefix are missing "
                "from info/files: %s" % ", ".join(prefix_not_in_files)
            )

    # Assert that no errors are detected
    assert len(errors) == 0, "\n".join(errors)


@contextlib.contextmanager
def put_bad_conda_on_path(testing_workdir):
    path_backup = os.environ["PATH"]
    # it is easier to add an intentionally bad path than it is to try to scrub any existing path
    os.environ["PATH"] = os.pathsep.join([testing_workdir, os.environ["PATH"]])

    exe_name = "conda.bat" if on_win else "conda"
    out_exe = os.path.join(testing_workdir, exe_name)
    with open(out_exe, "w") as f:
        f.write("exit 1")
    st = os.stat(out_exe)
    os.chmod(out_exe, st.st_mode | 0o111)
    try:
        yield
    except:
        raise
    finally:
        os.environ["PATH"] = path_backup


def get_noarch_python_meta(meta):
    d = meta.meta
    d["build"]["noarch"] = "python"
    return MetaData.fromdict(d, config=meta.config)


@pytest.fixture(autouse=True)
def skip_serial(request):
    if (
        request.node.get_marker("serial")
        and getattr(request.config, "slaveinput", {}).get("slaveid", "local") != "local"
    ):
        # under xdist and serial
        pytest.skip("serial")
