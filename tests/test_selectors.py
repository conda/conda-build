# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import sys
from itertools import product
from typing import TYPE_CHECKING

import pytest
from conda import __version__ as conda_version
from conda.base.context import context
from packaging.version import Version

from conda_build.config import Config
from conda_build.exceptions import CondaBuildUserError
from conda_build.selectors import get_selectors, select_lines
from conda_build.variants import DEFAULT_VARIANTS

if TYPE_CHECKING:
    from pytest import MonkeyPatch


def test_select_lines() -> None:
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


@pytest.mark.benchmark
def test_select_lines_battery() -> None:
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
                "\n".join(
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
                + "\n"
            )  # trailing newline
            assert select_lines(lines, namespace, variants_in_place=True) == selection


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
) -> None:
    monkeypatch.setenv("FEATURE_NOMKL", str(nomkl))

    config = Config(host_subdir=subdir)
    assert get_selectors(config) == {
        # defaults
        "build_platform": context.subdir,
        "lua": DEFAULT_VARIANTS["lua"],
        "luajit": DEFAULT_VARIANTS["lua"] == 2,
        "np": int(float(DEFAULT_VARIANTS["numpy"]) * 100),
        "os": os,
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
        "environ": os.environ,
        **os.environ,
        # override with True values
        **{key: True for key in expected},
    }


def test_select_lines_invalid() -> None:
    with pytest.raises(CondaBuildUserError, match=r"Invalid selector in meta\.yaml"):
        select_lines("text # [{bad]", {}, variants_in_place=True)
