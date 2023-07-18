# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
Module to handle generating test files.
"""
from __future__ import annotations

import json
import os
from os.path import basename, exists, isfile, join
from pathlib import Path

from .metadata import MetaData
from .utils import copy_into, ensure_list, on_win, rm_rf


def create_files(m: MetaData, test_dir: Path) -> bool:
    """
    Copy all test files from recipe over into testing directory.

    :param metadata: The meta.yaml object.
    :param test_dir: The testing directory.
    :return: Whether any test scripts copied were copied over.
    """
    patterns = ensure_list(m.get_value("test/files", []))
    for pattern in patterns:
        for file in Path(m.path).rglob(pattern):
            copy_into(
                file,
                test_dir / file.relative_to(m.path),
                m.config.timeout,
                locking=False,
                clobber=True,
            )
    return bool(patterns)


def _get_output_script_name(
    m: MetaData,
    win_status: bool,
) -> tuple[os.PathLike, os.PathLike]:
    # the way this works is that each output needs to explicitly define a test script to run.
    #   They do not automatically pick up run_test.*, but can be pointed at that explicitly.

    ext = ".bat" if win_status else ".sh"
    dst_name = "run_test" + ext
    src_name = dst_name
    if m.is_output:
        src_name = "no-file"
        for out in m.meta.get("outputs", []):
            if m.name() == out.get("name"):
                out_test_script = out.get("test", {}).get("script", "no-file")
                if os.path.splitext(out_test_script)[1].lower() == ext:
                    src_name = out_test_script
                    break
    return src_name, dst_name


def create_shell_files(m: MetaData, test_dir: os.PathLike) -> list[str]:
    win_status = [False, True] if m.noarch else [on_win]

    shell_files = []
    for status in win_status:
        src_name, dst_name = _get_output_script_name(m, status)
        dest_file = join(test_dir, dst_name)
        if exists(join(m.path, src_name)):
            # disable locking to avoid locking a temporary directory (the extracted test folder)
            copy_into(
                join(m.path, src_name),
                dest_file,
                m.config.timeout,
                locking=False,
            )
        commands = ensure_list(m.get_value("test/commands", []))
        if commands:
            with open(join(dest_file), "a") as f:
                f.write("\n\n")
                if not status:
                    f.write("set -ex\n\n")
                f.write("\n\n")
                for cmd in commands:
                    f.write(cmd)
                    f.write("\n")
                    if status:
                        f.write("IF %ERRORLEVEL% NEQ 0 exit /B 1\n")
                if status:
                    f.write("exit /B 0\n")
                else:
                    f.write("exit 0\n")
        if isfile(dest_file):
            shell_files.append(dest_file)
    return shell_files


def _create_test_files(
    m: MetaData,
    test_dir: os.PathLike,
    ext: str,
    comment_char: str = "# ",
) -> tuple[os.PathLike, bool]:
    name = "run_test" + ext
    if m.is_output:
        name = ""
        # the way this works is that each output needs to explicitly define a test script to run
        #   They do not automatically pick up run_test.*, but can be pointed at that explicitly.
        for out in m.meta.get("outputs", []):
            if m.name() == out.get("name"):
                out_test_script = out.get("test", {}).get("script", "no-file")
                if out_test_script.endswith(ext):
                    name = out_test_script
                    break

    out_file = join(test_dir, "run_test" + ext)
    if name:
        test_file = join(m.path, name)
        if isfile(test_file):
            with open(out_file, "w") as fo:
                fo.write(
                    f"{comment_char} tests for {m.dist()} (this is a generated file);\n"
                )
                fo.write("print('===== testing package: %s =====');\n" % m.dist())

                try:
                    with open(test_file) as fi:
                        fo.write(f"print('running {name}');\n")
                        fo.write(f"{comment_char} --- {name} (begin) ---\n")
                        fo.write(fi.read())
                        fo.write(f"{comment_char} --- {name} (end) ---\n")
                except AttributeError:
                    fo.write(
                        "# tests were not packaged with this module, and cannot be run\n"
                    )
                fo.write("\nprint('===== %s OK =====');\n" % m.dist())
    return (
        out_file,
        bool(name) and isfile(out_file) and basename(test_file) != "no-file",
    )


def create_py_files(m: MetaData, test_dir: os.PathLike) -> bool:
    tf, tf_exists = _create_test_files(m, test_dir, ".py")

    # Ways in which we can mark imports as none python imports
    # 1. preface package name with r-, lua- or perl-
    # 2. use list of dicts for test/imports, and have lang set in those dicts
    pkg_name = m.name()
    likely_r_pkg = pkg_name.startswith("r-")
    likely_lua_pkg = pkg_name.startswith("lua-")
    likely_perl_pkg = pkg_name.startswith("perl-")
    likely_non_python_pkg = likely_r_pkg or likely_lua_pkg or likely_perl_pkg

    if likely_non_python_pkg:
        imports = []
        for import_item in ensure_list(m.get_value("test/imports", [])):
            # add any imports specifically marked as python
            if (
                hasattr(import_item, "keys")
                and "lang" in import_item
                and import_item["lang"] == "python"
            ):
                imports.extend(import_item["imports"])
    else:
        imports = ensure_list(m.get_value("test/imports", []))
        imports = [
            item
            for item in imports
            if (
                not hasattr(item, "keys") or "lang" in item and item["lang"] == "python"
            )
        ]
    if imports:
        with open(tf, "a") as fo:
            for name in imports:
                fo.write('print("import: %r")\n' % name)
                fo.write("import %s\n" % name)
                fo.write("\n")
    return tf if (tf_exists or imports) else False


def create_r_files(m: MetaData, test_dir: os.PathLike) -> bool:
    tf, tf_exists = _create_test_files(m, test_dir, ".r")

    imports = None
    # two ways we can enable R import tests:
    # 1. preface package name with r- and just list imports in test/imports
    # 2. use list of dicts for test/imports, and have lang: 'r' set in one of those dicts
    if m.name().startswith("r-"):
        imports = ensure_list(m.get_value("test/imports", []))
    else:
        for import_item in ensure_list(m.get_value("test/imports", [])):
            if (
                hasattr(import_item, "keys")
                and "lang" in import_item
                and import_item["lang"] == "r"
            ):
                imports = import_item["imports"]
                break
    if imports:
        with open(tf, "a") as fo:
            for name in imports:
                fo.write('print("library(%r)")\n' % name)
                fo.write("library(%s)\n" % name)
                fo.write("\n")
    return tf if (tf_exists or imports) else False


def create_pl_files(m: MetaData, test_dir: os.PathLike) -> bool:
    tf, tf_exists = _create_test_files(m, test_dir, ".pl")

    imports = None
    if m.name().startswith("perl-"):
        imports = ensure_list(m.get_value("test/imports", []))
    else:
        for import_item in ensure_list(m.get_value("test/imports", [])):
            if (
                hasattr(import_item, "keys")
                and "lang" in import_item
                and import_item["lang"] == "perl"
            ):
                imports = import_item["imports"]
                break
    if tf_exists or imports:
        with open(tf, "a") as fo:
            print(r'my $expected_version = "%s";' % m.version().rstrip("0"), file=fo)
            if imports:
                for name in imports:
                    print(r'print("import: %s\n");' % name, file=fo)
                    print("use %s;\n" % name, file=fo)
                    # Don't try to print version for complex imports
                    if " " not in name:
                        print(
                            (
                                "if (defined {0}->VERSION) {{\n"
                                + "\tmy $given_version = {0}->VERSION;\n"
                                + "\t$given_version =~ s/0+$//;\n"
                                + "\tdie('Expected version ' . $expected_version . ' but"
                                + " found ' . $given_version) unless ($expected_version "
                                + "eq $given_version);\n"
                                + "\tprint('\tusing version ' . {0}->VERSION . '\n');\n"
                                + "\n}}"
                            ).format(name),
                            file=fo,
                        )
    return tf if (tf_exists or imports) else False


def create_lua_files(m: MetaData, test_dir: os.PathLike) -> bool:
    tf, tf_exists = _create_test_files(m, test_dir, ".lua")

    imports = None
    if m.name().startswith("lua-"):
        imports = ensure_list(m.get_value("test/imports", []))
    else:
        for import_item in ensure_list(m.get_value("test/imports", [])):
            if (
                hasattr(import_item, "keys")
                and "lang" in import_item
                and import_item["lang"] == "lua"
            ):
                imports = import_item["imports"]
                break
    if imports:
        with open(tf, "a+") as fo:
            for name in imports:
                print(r'print("require \"%s\"\n");' % name, file=fo)
                print('require "%s"\n' % name, file=fo)
    return tf if (tf_exists or imports) else False


def create_all_test_files(
    m: MetaData,
    test_dir: os.PathLike | None = None,
) -> tuple[bool, bool, bool, bool, bool, list[str]]:
    if test_dir:
        # this happens when we're finishing the build
        rm_rf(test_dir)
        os.makedirs(test_dir, exist_ok=True)
        test_requires = ensure_list(m.get_value("test/requires", []))
        if test_requires:
            Path(test_dir, "test_time_dependencies.json").write_text(
                json.dumps(test_requires)
            )
    else:
        # this happens when we're running a package's tests
        test_dir = m.config.test_dir
        os.makedirs(test_dir, exist_ok=True)

    return (
        create_files(m, Path(test_dir)),
        create_pl_files(m, test_dir),
        create_py_files(m, test_dir),
        create_r_files(m, test_dir),
        create_lua_files(m, test_dir),
        create_shell_files(m, test_dir),
    )
