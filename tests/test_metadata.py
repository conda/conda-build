# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import subprocess

import pytest

from conda_build import api
from conda_build.metadata import MetaData, _hash_dependencies, select_lines
from conda_build.utils import DEFAULT_SUBDIRS

from .utils import metadata_dir, thisdir


def test_uses_vcs_in_metadata(testing_workdir, testing_metadata):
    testing_metadata._meta_path = os.path.join(testing_workdir, "meta.yaml")
    testing_metadata._meta_name = "meta.yaml"
    with open(testing_metadata.meta_path, "w") as f:
        f.write("http://hg.something.com")
    assert not testing_metadata.uses_vcs_in_meta
    assert not testing_metadata.uses_vcs_in_build
    with open(testing_metadata.meta_path, "w") as f:
        f.write("hg something something")
    assert not testing_metadata.uses_vcs_in_meta
    assert testing_metadata.uses_vcs_in_build
    with open(testing_metadata.meta_path, "w") as f:
        f.write("hg.exe something something")
    assert not testing_metadata.uses_vcs_in_meta
    assert testing_metadata.uses_vcs_in_build
    with open(testing_metadata.meta_path, "w") as f:
        f.write("HG_WEEEEE")
    assert testing_metadata.uses_vcs_in_meta
    assert not testing_metadata.uses_vcs_in_build


def test_select_lines():
    lines = """
test
test [abc] no
test [abc] # no

test [abc]
 'quoted # [abc] '
 "quoted # [abc] yes "
test # stuff [abc] yes
test {{ JINJA_VAR[:2] }}
test {{ JINJA_VAR[:2] }} # stuff [abc] yes
test {{ JINJA_VAR[:2] }} # stuff yes [abc]
test {{ JINJA_VAR[:2] }} # [abc] stuff yes
{{ environ["test"] }}  # [abc]
"""

    assert (
        select_lines(lines, {"abc": True}, variants_in_place=True)
        == """
test
test [abc] no
test [abc] # no

test
 'quoted'
 "quoted"
test
test {{ JINJA_VAR[:2] }}
test {{ JINJA_VAR[:2] }}
test {{ JINJA_VAR[:2] }}
test {{ JINJA_VAR[:2] }}
{{ environ["test"] }}
"""
    )
    assert (
        select_lines(lines, {"abc": False}, variants_in_place=True)
        == """
test
test [abc] no
test [abc] # no

test {{ JINJA_VAR[:2] }}
"""
    )


def test_disallow_leading_period_in_version(testing_metadata):
    testing_metadata.meta["package"]["version"] = ".ste.ve"
    testing_metadata.final = True
    with pytest.raises(ValueError):
        testing_metadata.version()


def test_disallow_dash_in_features(testing_metadata):
    testing_metadata.meta["build"]["features"] = ["abc"]
    testing_metadata.parse_again()
    with pytest.raises(ValueError):
        testing_metadata.meta["build"]["features"] = ["ab-c"]
        testing_metadata.parse_again()


def test_append_section_data(testing_metadata):
    testing_metadata.final = False
    testing_metadata.parse_again()
    requirements_len = len(testing_metadata.meta["requirements"].get("build", []))
    testing_metadata.config.append_sections_file = os.path.join(
        thisdir, "test-append.yaml"
    )
    testing_metadata.final = False
    testing_metadata.parse_again()
    assert len(testing_metadata.meta["requirements"]["build"]) == requirements_len + 1
    assert "frank" in testing_metadata.meta["requirements"]["build"]


def test_clobber_section_data(testing_metadata):
    testing_metadata.config.clobber_sections_file = os.path.join(
        thisdir, "test-clobber.yaml"
    )
    testing_metadata.final = False
    testing_metadata.parse_again()
    # a field that should be clobbered
    testing_metadata.meta["about"]["summary"] = "yep"
    # a field that should stay the same
    testing_metadata.meta["about"]["home"] = "sweet home"


@pytest.mark.serial
def test_build_bootstrap_env_by_name(testing_metadata):
    assert not any(
        "git" in pkg for pkg in testing_metadata.meta["requirements"].get("build", [])
    ), testing_metadata.meta["requirements"].get("build", [])
    try:
        cmd = "conda create -y -n conda_build_bootstrap_test git"
        subprocess.check_call(cmd.split())
        testing_metadata.config.bootstrap = "conda_build_bootstrap_test"
        testing_metadata.final = False
        testing_metadata.parse_again()
        assert any(
            "git" in pkg for pkg in testing_metadata.meta["requirements"]["build"]
        ), testing_metadata.meta["requirements"]["build"]
    finally:
        cmd = "conda remove -y -n conda_build_bootstrap_test --all"
        subprocess.check_call(cmd.split())


def test_build_bootstrap_env_by_path(testing_metadata):
    assert not any(
        "git" in pkg for pkg in testing_metadata.meta["requirements"].get("build", [])
    ), testing_metadata.meta["requirements"].get("build", [])
    path = os.path.join(thisdir, "conda_build_bootstrap_test")
    try:
        cmd = f"conda create -y -p {path} git"
        subprocess.check_call(cmd.split())
        testing_metadata.config.bootstrap = path
        testing_metadata.final = False
        testing_metadata.parse_again()
        assert any(
            "git" in pkg for pkg in testing_metadata.meta["requirements"]["build"]
        ), testing_metadata.meta["requirements"]["build"]
    finally:
        cmd = f"conda remove -y -p {path} --all"
        subprocess.check_call(cmd.split())


@pytest.mark.parametrize(
    "platform,arch,python,compilers",
    [
        ("win", "x86_64", "2.7", {"vs2008_win-x86_64"}),
        ("win", "x86_64", "3.1", {"vs2008_win-x86_64"}),
        ("win", "x86_64", "3.2", {"vs2008_win-x86_64"}),
        ("win", "x86_64", "3.3", {"vs2010_win-x86_64"}),
        ("win", "x86_64", "3.4", {"vs2010_win-x86_64"}),
        ("win", "x86_64", "3.5", {"vs2017_win-x86_64"}),
        ("win", "x86_64", "3.6", {"vs2017_win-x86_64"}),
        ("win", "x86_64", "3.7", {"vs2017_win-x86_64"}),
        ("win", "x86_64", "3.8", {"vs2017_win-x86_64"}),
        ("win", "x86_64", "3.9", {"vs2017_win-x86_64"}),
        ("win", "x86_64", "3.10", {"vs2017_win-x86_64"}),
        ("win", "x86_64", "3.11", {"vs2017_win-x86_64"}),
        ("linux", "32", "3.11", {"gcc_linux-32", "gxx_linux-32"}),
        ("linux", "64", "3.11", {"gcc_linux-64", "gxx_linux-64"}),
        ("osx", "32", "3.11", {"clang_osx-32", "clangxx_osx-32"}),
        ("osx", "64", "3.11", {"clang_osx-64", "clangxx_osx-64"}),
    ],
)
def test_native_compiler_metadata(
    platform: str, arch: str, python: str, compilers: set[str], testing_config
):
    testing_config.platform = platform
    metadata = api.render(
        os.path.join(metadata_dir, "_compiler_jinja2"),
        config=testing_config,
        variants={"target_platform": f"{platform}-{arch}"},
        permit_unsatisfiable_variants=True,
        finalize=False,
        bypass_env_check=True,
        python=python,
    )[0][0]
    assert compilers <= set(metadata.meta["requirements"]["build"])


def test_compiler_metadata_cross_compiler():
    variant = {
        "c_compiler": "c-compiler-linux",
        "cxx_compiler": "cxx-compiler-linux",
        "fortran_compiler": "fortran-compiler-linux",
        "target_platform": "osx-109-x86_64",
    }
    metadata = MetaData(os.path.join(metadata_dir, "_compiler_jinja2"), variant=variant)
    assert "c-compiler-linux_osx-109-x86_64" in metadata.meta["requirements"]["build"]
    assert "cxx-compiler-linux_osx-109-x86_64" in metadata.meta["requirements"]["build"]
    assert (
        "fortran-compiler-linux_osx-109-x86_64"
        in metadata.meta["requirements"]["build"]
    )


def test_hash_build_id(testing_metadata):
    testing_metadata.config.variant["zlib"] = "1.2"
    testing_metadata.meta["requirements"]["host"] = ["zlib"]
    testing_metadata.final = True
    hash_contents = testing_metadata.get_hash_contents()
    assert hash_contents["zlib"] == "1.2"
    hdeps = testing_metadata.hash_dependencies()
    hash_contents_tp = hash_contents.copy()
    found = False
    for subdir in DEFAULT_SUBDIRS:
        hash_contents_tp["target_platform"] = subdir
        hdeps_tp = _hash_dependencies(
            hash_contents_tp, testing_metadata.config.hash_length
        )
        if hdeps_tp == hdeps:
            found = True
            break
    assert (
        found
    ), f"Did not find build that matched {hdeps} when testing each of DEFAULT_SUBDIRS"
    assert testing_metadata.build_id() == hdeps + "_1"


def test_hash_build_id_key_order(testing_metadata):
    deps = testing_metadata.meta["requirements"].get("build", [])[:]

    # first, prepend
    newdeps = deps[:]
    newdeps.insert(0, "steve")
    testing_metadata.meta["requirements"]["build"] = newdeps
    hash_pre = testing_metadata.hash_dependencies()

    # next, append
    newdeps = deps[:]
    newdeps.append("steve")
    testing_metadata.meta["requirements"]["build"] = newdeps
    hash_post = testing_metadata.hash_dependencies()

    # make sure they match
    assert hash_pre == hash_post


def test_config_member_decoupling(testing_metadata):
    testing_metadata.config.some_member = "abc"
    b = testing_metadata.copy()
    b.config.some_member = "123"
    assert b.config.some_member != testing_metadata.config.some_member
