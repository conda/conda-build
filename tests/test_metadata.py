# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import subprocess
from contextlib import nullcontext
from typing import TYPE_CHECKING

import pytest

from conda_build import api, metadata
from conda_build.exceptions import CondaBuildUserError
from conda_build.metadata import (
    FIELDS,
    OPTIONALLY_ITERABLE_FIELDS,
    MetaData,
    _hash_dependencies,
    check_bad_chrs,
    sanitize,
    yamlize,
)
from conda_build.utils import DEFAULT_SUBDIRS

from .utils import metadata_dir, metadata_path, thisdir

if TYPE_CHECKING:
    from pathlib import Path


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
@pytest.mark.filterwarnings("ignore", category=PendingDeprecationWarning)
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


@pytest.mark.filterwarnings("ignore", category=PendingDeprecationWarning)
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
        ("win", "x86_64", "3.12", {"vs2017_win-x86_64"}),
        ("linux", "32", "3.12", {"gcc_linux-32", "gxx_linux-32"}),
        ("linux", "64", "3.12", {"gcc_linux-64", "gxx_linux-64"}),
        ("osx", "32", "3.12", {"clang_osx-32", "clangxx_osx-32"}),
        ("osx", "64", "3.12", {"clang_osx-64", "clangxx_osx-64"}),
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


@pytest.mark.parametrize(
    "platform,arch,stdlib,stdlib_version",
    [
        ("linux", "64", "sysroot", "2.12"),
        ("linux", "aarch64", "sysroot", "2.17"),
        ("osx", "64", "macosx_deployment_target", "10.13"),
        ("osx", "arm64", "macosx_deployment_target", "11.0"),
    ],
)
def test_native_stdlib_metadata(
    platform: str, arch: str, stdlib: str, stdlib_version: str, testing_config
):
    testing_config.platform = platform
    metadata = api.render(
        os.path.join(metadata_dir, "_stdlib_jinja2"),
        config=testing_config,
        variants={"target_platform": f"{platform}-{arch}"},
        platform=platform,
        arch=arch,
        permit_unsatisfiable_variants=True,
        finalize=False,
        bypass_env_check=True,
        python="3.11",  # irrelevant
    )[0][0]
    stdlib_req = f"{stdlib}_{platform}-{arch} {stdlib_version}.*"
    assert stdlib_req in metadata.meta["requirements"]["host"]
    assert {"c_stdlib", "c_stdlib_version"} <= metadata.get_used_vars()
    hash_contents = metadata.get_hash_contents()
    assert stdlib == hash_contents["c_stdlib"]
    assert stdlib_version == hash_contents["c_stdlib_version"]


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


# ensure that numbers are not interpreted as ints or floats, doing so trips up versions
# with trailing zeros
def test_yamlize_zero():
    yml = yamlize(
        """
        - 0
        - 0.
        - 0.0
        - .0
        """
    )

    assert yml == ["0", "0.", "0.0", ".0"]


def test_yamlize_positive():
    yml = yamlize(
        """
        - +1
        - +1.
        - +1.2
        - +.2
        """
    )

    assert yml == ["+1", "+1.", "+1.2", "+.2"]


def test_yamlize_negative():
    yml = yamlize(
        """
        - -1
        - -1.
        - -1.2
        - -.2
        """
    )

    assert yml == ["-1", "-1.", "-1.2", "-.2"]


def test_yamlize_numbers():
    yml = yamlize(
        """
        - 1
        - 1.2
        """
    )

    assert yml == ["1", "1.2"]


def test_yamlize_versions():
    yml = yamlize(
        """
        - 1.2.3
        - 1.2.3.4
        """
    )

    assert yml == ["1.2.3", "1.2.3.4"]


def test_fromstring():
    MetaData.fromstring((metadata_path / "multiple_sources" / "meta.yaml").read_text())


def test_fromdict():
    MetaData.fromdict(
        yamlize((metadata_path / "multiple_sources" / "meta.yaml").read_text())
    )


def test_get_section(testing_metadata: MetaData):
    for name in FIELDS:
        section = testing_metadata.get_section(name)
        if name in OPTIONALLY_ITERABLE_FIELDS:
            assert isinstance(section, list)
        else:
            assert isinstance(section, dict)


@pytest.mark.parametrize(
    "keys,expected",
    [
        pytest.param([], {}, id="git_tag"),
        pytest.param(["git_tag"], {"git_rev": "rev"}, id="git_tag"),
        pytest.param(["git_branch"], {"git_rev": "rev"}, id="git_branch"),
        pytest.param(["git_rev"], {"git_rev": "rev"}, id="git_rev"),
        pytest.param(["git_tag", "git_branch"], None, id="git_tag + git_branch"),
        pytest.param(["git_tag", "git_rev"], None, id="git_tag + git_rev"),
        pytest.param(["git_branch", "git_rev"], None, id="git_branch + git_rev"),
        pytest.param(
            ["git_tag", "git_branch", "git_rev"],
            None,
            id="git_tag + git_branch + git_rev",
        ),
    ],
)
def test_sanitize_source(keys: list[str], expected: dict[str, str] | None) -> None:
    with pytest.raises(
        CondaBuildUserError,
        match=r"Multiple git_revs:",
    ) if expected is None else nullcontext():
        assert sanitize({"source": {key: "rev" for key in keys}}) == {
            "source": expected
        }


@pytest.mark.parametrize(
    "value,field,invalid",
    [
        pytest.param("good", "field", None, id="valid field"),
        pytest.param("!@d&;-", "field", "!&;@", id="invalid field"),
        pytest.param("good", "package/version", None, id="valid package/version"),
        pytest.param("!@d&;-", "package/version", "&-;@", id="invalid package/version"),
        pytest.param("good", "build/string", None, id="valid build/string"),
        pytest.param("!@d&;-", "build/string", "!&-;@", id="invalid build/string"),
    ],
)
def test_check_bad_chrs(value: str, field: str, invalid: str) -> None:
    with pytest.raises(
        CondaBuildUserError,
        match=rf"Bad character\(s\) \({invalid}\) in {field}: {value}\.",
    ) if invalid else nullcontext():
        check_bad_chrs(value, field)


def test_parse_until_resolved(testing_metadata: MetaData, tmp_path: Path) -> None:
    (recipe := tmp_path / (name := "meta.yaml")).write_text("{{ UNDEFINED[:2] }}")
    testing_metadata._meta_path = recipe
    testing_metadata._meta_name = name

    with pytest.raises(
        CondaBuildUserError,
        match=("Failed to render jinja template"),
    ):
        testing_metadata.parse_until_resolved()


def test_parse_until_resolved_skip_avoids_undefined_jinja(
    testing_metadata: MetaData, tmp_path: Path
) -> None:
    (recipe := tmp_path / (name := "meta.yaml")).write_text(
        """
package:
    name: dummy
    version: {{version}}
build:
    skip: True
"""
    )
    testing_metadata._meta_path = recipe
    testing_metadata._meta_name = name

    # because skip is True, we should not error out here - so no exception should be raised
    try:
        testing_metadata.parse_until_resolved()
    except CondaBuildUserError:
        pytest.fail(
            "Undefined variable caused error, even though this build is skipped"
        )


@pytest.mark.parametrize(
    "function,raises",
    [
        ("ARCH_MAP", TypeError),
        ("get_selectors", TypeError),
        ("ns_cfg", TypeError),
        ("sel_pat", TypeError),
        ("parseNameNotFound", TypeError),
        ("eval_selector", TypeError),
        ("_split_line_selector", TypeError),
        ("select_lines", TypeError),
    ],
)
def test_deprecations(function: str, raises: type[Exception] | None) -> None:
    raises_context = pytest.raises(raises) if raises else nullcontext()
    with pytest.deprecated_call(), raises_context:
        getattr(metadata, function)()
