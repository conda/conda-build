# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
# This file makes sure that our API has not changed.  Doing so can not be accidental.  Whenever it
#    happens, we should bump our major build number, because we may have broken someone.

import inspect
import sys

import pytest

from conda_build import api

pytestmark = pytest.mark.no_default_testing_config


def argspec_defaults(argspec):
    return tuple(parameter.default for parameter in argspec.parameters.values())


def test_api_config():
    assert hasattr(api, "Config")
    assert hasattr(api, "get_or_merge_config")


def test_api_get_or_merge_config():
    argspec = inspect.signature(api.get_or_merge_config)
    assert list(argspec.parameters) == ["config", "variant", "kwargs"]
    assert argspec_defaults(argspec) == (inspect._empty, None, inspect._empty)


def test_api_render():
    argspec = inspect.signature(api.render)
    assert list(argspec.parameters) == [
        "recipe_path",
        "config",
        "variants",
        "permit_unsatisfiable_variants",
        "finalize",
        "bypass_env_check",
        "kwargs",
    ]
    assert argspec_defaults(argspec) == (
        inspect._empty,
        None,
        None,
        True,
        True,
        False,
        inspect._empty,
    )


def test_api_output_yaml():
    argspec = inspect.signature(api.output_yaml)
    assert list(argspec.parameters) == ["metadata", "file_path", "suppress_outputs"]
    assert argspec_defaults(argspec) == (inspect._empty, None, False)


def test_api_get_output_file_path():
    argspec = inspect.signature(api.get_output_file_path)
    assert list(argspec.parameters) == [
        "recipe_path_or_metadata",
        "no_download_source",
        "config",
        "variants",
        "kwargs",
    ]
    assert argspec_defaults(argspec) == (
        inspect._empty,
        False,
        None,
        None,
        inspect._empty,
    )


def test_api_check():
    argspec = inspect.signature(api.check)
    assert list(argspec.parameters) == [
        "recipe_path",
        "no_download_source",
        "config",
        "variants",
        "kwargs",
    ]
    assert argspec_defaults(argspec) == (
        inspect._empty,
        False,
        None,
        None,
        inspect._empty,
    )


def test_api_build():
    argspec = inspect.signature(api.build)
    assert list(argspec.parameters) == [
        "recipe_paths_or_metadata",
        "post",
        "need_source_download",
        "build_only",
        "notest",
        "config",
        "variants",
        "stats",
        "kwargs",
    ]
    assert argspec_defaults(argspec) == (
        inspect._empty,
        None,
        True,
        False,
        False,
        None,
        None,
        None,
        inspect._empty,
    )


def test_api_test():
    argspec = inspect.signature(api.test)
    assert list(argspec.parameters) == [
        "recipedir_or_package_or_metadata",
        "move_broken",
        "config",
        "stats",
        "kwargs",
    ]
    assert argspec_defaults(argspec) == (
        inspect._empty,
        True,
        None,
        None,
        inspect._empty,
    )


def test_api_list_skeletons():
    argspec = inspect.signature(api.list_skeletons)
    assert list(argspec.parameters) == []
    assert argspec_defaults(argspec) == ()


def test_api_skeletonize():
    argspec = inspect.signature(api.skeletonize)
    assert list(argspec.parameters) == [
        "packages",
        "repo",
        "output_dir",
        "version",
        "recursive",
        "config",
        "kwargs",
    ]
    assert argspec_defaults(argspec) == (
        inspect._empty,
        inspect._empty,
        ".",
        None,
        False,
        None,
        inspect._empty,
    )


def test_api_develop():
    argspec = inspect.signature(api.develop)
    assert list(argspec.parameters) == [
        "recipe_dir",
        "prefix",
        "no_pth_file",
        "build_ext",
        "clean",
        "uninstall",
    ]
    assert argspec_defaults(argspec) == (
        inspect._empty,
        sys.prefix,
        False,
        False,
        False,
        False,
    )


def test_api_convert():
    argspec = inspect.signature(api.convert)
    assert list(argspec.parameters) == [
        "package_file",
        "output_dir",
        "show_imports",
        "platforms",
        "force",
        "dependencies",
        "verbose",
        "quiet",
        "dry_run",
    ]
    assert argspec_defaults(argspec) == (
        inspect._empty,
        ".",
        False,
        None,
        False,
        None,
        False,
        True,
        False,
    )


def test_api_installable():
    argspec = inspect.signature(api.test_installable)
    assert list(argspec.parameters) == ["channel"]
    assert argspec_defaults(argspec) == ("defaults",)


def test_api_inspect_linkages():
    argspec = inspect.signature(api.inspect_linkages)
    assert list(argspec.parameters) == [
        "packages",
        "prefix",
        "untracked",
        "all_packages",
        "show_files",
        "groupby",
        "sysroot",
    ]
    assert argspec_defaults(argspec) == (
        inspect._empty,
        sys.prefix,
        False,
        False,
        False,
        "package",
        "",
    )


def test_api_inspect_objects():
    argspec = inspect.signature(api.inspect_objects)
    assert list(argspec.parameters) == ["packages", "prefix", "groupby"]
    assert argspec_defaults(argspec) == (inspect._empty, sys.prefix, "filename")


def test_api_inspect_prefix_length():
    argspec = inspect.signature(api.inspect_prefix_length)
    assert list(argspec.parameters) == ["packages", "min_prefix_length"]
    # hard-coded prefix length as intentional check here
    assert argspec_defaults(argspec) == (inspect._empty, 255)


def test_api_create_metapackage():
    argspec = inspect.signature(api.create_metapackage)
    assert list(argspec.parameters) == [
        "name",
        "version",
        "entry_points",
        "build_string",
        "build_number",
        "dependencies",
        "home",
        "license_name",
        "summary",
        "config",
        "kwargs",
    ]
    assert argspec_defaults(argspec) == (
        inspect._empty,
        inspect._empty,
        (),
        None,
        0,
        (),
        None,
        None,
        None,
        None,
        inspect._empty,
    )


def test_api_update_index():
    # getfullargspec() isn't friends with functools.wraps
    argspec = inspect.signature(api.update_index)
    assert list(argspec.parameters) == [
        "dir_paths",
        "config",
        "force",
        "check_md5",
        "remove",
        "channel_name",
        "subdir",
        "threads",
        "patch_generator",
        "verbose",
        "progress",
        "hotfix_source_repo",
        "current_index_versions",
        "kwargs",
    ]
    assert tuple(parameter.default for parameter in argspec.parameters.values()) == (
        inspect._empty,
        None,
        False,
        False,
        False,
        None,
        None,
        None,
        None,
        False,
        False,
        None,
        None,
        inspect._empty,
    )
