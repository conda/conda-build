# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import subprocess
import sys
from contextlib import nullcontext
from itertools import product
from typing import TYPE_CHECKING

import evalidate
import pytest
from conda import __version__ as conda_version
from conda.base.context import context
from packaging.version import Version

from conda_build import api
from conda_build.config import Config
from conda_build.exceptions import CondaBuildUserError
from conda_build.metadata import (
    FIELDS,
    OPTIONALLY_ITERABLE_FIELDS,
    MetaData,
    OSModuleSubset,
    _hash_dependencies,
    check_bad_chrs,
    eval_selector,
    get_selectors,
    sanitize,
    select_lines,
    yamlize,
)
from conda_build.utils import DEFAULT_SUBDIRS
from conda_build.variants import DEFAULT_VARIANTS

from .utils import metadata_dir, metadata_path, thisdir

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


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
    lines = "\n".join(
        (
            "",  # preserve leading newline
            "test",
            "test [abc] no",
            "test [abc] # no",
            " ' test ' ",
            ' " test " ',
            "",  # preserve newline
            "# comment line",  # preserve comment line (but not the comment)
            "test [abc]",
            " 'quoted # [abc] '",
            ' "quoted # [abc] yes "',
            "test # stuff [abc] yes",
            "test {{ JINJA_VAR[:2] }}",
            "test {{ JINJA_VAR[:2] }} # stuff [abc] yes",
            "test {{ JINJA_VAR[:2] }} # stuff yes [abc]",
            "test {{ JINJA_VAR[:2] }} # [abc] stuff yes",
            '{{ environ["test"] }}  # [abc]',
            "",  # preserve trailing newline
        )
    )

    assert select_lines(lines, {"abc": True}, variants_in_place=True) == "\n".join(
        (
            "",  # preserve leading newline
            "test",
            "test [abc] no",
            "test [abc] # no",
            " ' test '",
            ' " test "',
            "",  # preserve newline
            "",  # preserve comment line (but not the comment)
            "test",
            " 'quoted'",
            ' "quoted"',
            "test",
            "test {{ JINJA_VAR[:2] }}",
            "test {{ JINJA_VAR[:2] }}",
            "test {{ JINJA_VAR[:2] }}",
            "test {{ JINJA_VAR[:2] }}",
            '{{ environ["test"] }}',
            "",  # preserve trailing newline
        )
    )
    assert select_lines(lines, {"abc": False}, variants_in_place=True) == "\n".join(
        (
            "",  # preserve leading newline
            "test",
            "test [abc] no",
            "test [abc] # no",
            " ' test '",
            ' " test "',
            "",  # preserve newline
            "",  # preserve comment line (but not the comment)
            "test {{ JINJA_VAR[:2] }}",
            "",  # preserve trailing newline
        )
    )


@pytest.mark.parametrize("unsafe", (True, False))
def test_select_access_environ(testing_config, unsafe):
    namespace = get_selectors(testing_config)
    assert "NOTFOUND" == eval_selector(
        "environ.get('DOESNOTEXIST', 'NOTFOUND')",
        namespace,
        variants_in_place=True,
        unsafe=unsafe,
    )
    assert "NOTFOUND" == eval_selector(
        "os.environ.get('DOESNOTEXIST', 'NOTFOUND')",
        namespace,
        variants_in_place=True,
        unsafe=unsafe,
    )


def test_select_evalidate_model():
    from evalidate.security import test_security

    from conda_build.metadata import evalidate_model

    assert test_security(model=evalidate_model())


@pytest.mark.parametrize("unsafe", (True, False))
@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo BAD')",
        "os.getenv.__globals__['system']('echo BAD')",
        "getattr(os.getenv, '__globals__')['system']('echo BAD')",
        "os.environ.update({'BLAH': 'BAD'})",
        "os.environ.setdefault('BLAH', 'BAD')",
    ],
)
def test_select_malicious(testing_config, expression, unsafe):
    namespace = get_selectors(testing_config)
    with nullcontext() if unsafe else pytest.raises(evalidate.ValidationException):
        eval_selector(
            expression,
            namespace,
            variants_in_place=True,
            unsafe=unsafe,
        )


@pytest.mark.benchmark
def test_select_lines_battery():
    test_foo = "test [foo]"
    test_bar = "test [bar]"
    test_baz = "test [baz]"
    test_foo_and_bar = "test [foo and bar]"
    test_foo_and_baz = "test [foo and baz]"
    test_foo_or_bar = "test [foo or bar]"
    test_foo_or_baz = "test [foo or baz]"

    lines = "\n".join(
        (
            test_foo,
            test_bar,
            test_baz,
            test_foo_and_bar,
            test_foo_and_baz,
            test_foo_or_bar,
            test_foo_or_baz,
        )
        * 10
    )

    for _ in range(10):
        for foo, bar, baz in product((True, False), repeat=3):
            namespace = {"foo": foo, "bar": bar, "baz": baz}
            selection = (
                ["test"]
                * (
                    foo
                    + bar
                    + baz
                    + (foo and bar)
                    + (foo and baz)
                    + (foo or bar)
                    + (foo or baz)
                )
                * 10
            )
            selection = "\n".join(selection) + "\n"  # trailing newline
            assert select_lines(lines, namespace, variants_in_place=True) == selection


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
    assert found, (
        f"Did not find build that matched {hdeps} when testing each of DEFAULT_SUBDIRS"
    )
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


OS_ARCH: tuple[str, ...] = (
    "aarch64",
    "arm",
    "arm64",
    "armv6l",
    "armv7l",
    "linux",
    "linux32",
    "linux64",
    "osx",
    "ppc64",
    "ppc64le",
    "s390x",
    "unix",
    "win",
    "win32",
    "win64",
    "x86",
    "x86_64",
    "z",
    "zos",
)

if Version(conda_version) >= Version("23.3"):
    OS_ARCH = (*OS_ARCH, "riscv64")

if Version(conda_version) >= Version("23.7"):
    OS_ARCH = (*OS_ARCH, "freebsd")

if Version(conda_version) >= Version("23.9"):
    OS_ARCH = (*OS_ARCH, "emscripten", "wasi", "wasm32")


@pytest.mark.parametrize(
    (
        "subdir",  # defined in conda.base.constants.KNOWN_SUBDIRS
        "expected",  # OS_ARCH keys expected to be True
    ),
    [
        ("emscripten-wasm32", {"unix", "emscripten", "wasm32"}),
        ("wasi-wasm32", {"wasi", "wasm32"}),
        ("freebsd-64", {"freebsd", "x86", "x86_64"}),
        ("linux-32", {"unix", "linux", "linux32", "x86"}),
        ("linux-64", {"unix", "linux", "linux64", "x86", "x86_64"}),
        ("linux-aarch64", {"unix", "linux", "aarch64"}),
        ("linux-armv6l", {"unix", "linux", "arm", "armv6l"}),
        ("linux-armv7l", {"unix", "linux", "arm", "armv7l"}),
        ("linux-ppc64", {"unix", "linux", "ppc64"}),
        ("linux-ppc64le", {"unix", "linux", "ppc64le"}),
        ("linux-riscv64", {"unix", "linux", "riscv64"}),
        ("linux-s390x", {"unix", "linux", "s390x"}),
        ("osx-64", {"unix", "osx", "x86", "x86_64"}),
        ("osx-arm64", {"unix", "osx", "arm64"}),
        ("win-32", {"win", "win32", "x86"}),
        ("win-64", {"win", "win64", "x86", "x86_64"}),
        ("win-arm64", {"win", "arm64"}),
        ("zos-z", {"zos", "z"}),
    ],
)
@pytest.mark.parametrize("nomkl", [0, 1])
def test_get_selectors(
    monkeypatch: MonkeyPatch,
    subdir: str,
    expected: set[str],
    nomkl: int,
):
    monkeypatch.setenv("FEATURE_NOMKL", str(nomkl))

    config = Config(host_subdir=subdir)
    assert get_selectors(config) == {
        # defaults
        "build_platform": context.subdir,
        "lua": DEFAULT_VARIANTS["lua"],
        "luajit": DEFAULT_VARIANTS["lua"] == 2,
        "np": int(float(DEFAULT_VARIANTS["numpy"]) * 100),
        "os": OSModuleSubset,
        "pl": DEFAULT_VARIANTS["perl"],
        "py": int(f"{sys.version_info.major}{sys.version_info.minor}"),
        "py26": sys.version_info[:2] == (2, 6),
        "py27": sys.version_info[:2] == (2, 7),
        "py2k": sys.version_info.major == 2,
        "py33": sys.version_info[:2] == (3, 3),
        "py34": sys.version_info[:2] == (3, 4),
        "py35": sys.version_info[:2] == (3, 5),
        "py36": sys.version_info[:2] == (3, 6),
        "py3k": sys.version_info.major == 3,
        "nomkl": bool(nomkl),
        # default OS/arch values
        **{key: False for key in OS_ARCH},
        # environment variables
        "environ": OSModuleSubset.environ,
        **os.environ,
        # override with True values
        **{key: True for key in expected},
    }


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


def test_select_lines_invalid():
    with pytest.raises(
        CondaBuildUserError,
        match=r"Invalid selector in meta\.yaml",
    ):
        select_lines("text # [{bad]", {}, variants_in_place=True)


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
    with (
        pytest.raises(
            CondaBuildUserError,
            match=r"Multiple git_revs:",
        )
        if expected is None
        else nullcontext()
    ):
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
    with (
        pytest.raises(
            CondaBuildUserError,
            match=rf"Bad character\(s\) \({invalid}\) in {field}: {value}\.",
        )
        if invalid
        else nullcontext()
    ):
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


@pytest.mark.parametrize("have_variant", [True, False])
def test_parse_until_resolved_missing_jinja_in_spec(
    testing_metadata: MetaData,
    tmp_path: Path,
    have_variant: bool,
) -> None:
    (recipe := tmp_path / (name := "meta.yaml")).write_text(
        """
package:
    name: dummy
    version: 1.0.0

build:
    noarch: python
    number: 0

requirements:
    host:
        - python ={{ python_min }}
    run:
        - python >={{ python_min }}
"""
    )
    (tmp_path / "conda_build_config.yaml").write_text(
        """
python_min:
    - 3.6
"""
    )
    testing_metadata._meta_path = recipe
    testing_metadata._meta_name = name
    if have_variant:
        testing_metadata.config.variant = {"python_min": "3.6"}
    else:
        delattr(testing_metadata.config, "variant")
        delattr(testing_metadata.config, "variant_config_files")
        delattr(testing_metadata.config, "variants")

    try:
        testing_metadata.parse_until_resolved()
        if not have_variant:
            pytest.fail("Undefined variable did NOT cause spec parsing error!")
        else:
            print("parsed OK!")
    except (Exception, SystemExit):
        if have_variant:
            pytest.fail(
                "Undefined variable caused spec parsing error even if we have the variant!"
            )
        else:
            print("did not parse OK!")


def test_extract_single_output_text_with_jinja_is_broken():
    """
    Given a recipe with three outputs 1, 2, and 3, where 2 is guarded by a falsy Jinja-if,
    MetaData.extract_single_output_text() returns 2 when asked for 3.

    This is a bug that should be fixed.
    """
    metadata = MetaData(os.path.join(metadata_dir, "_jinja_outputs"))
    output = metadata.extract_single_output_text(
        "output3", getattr(metadata, "type", None)
    )
    # We of course want to obtain output3, but the buggy behaviour gave us output2.
    assert "output3" not in output
    assert "output2" in output
