# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
# This file makes sure that our API has not changed.  Doing so can not be accidental.  Whenever it
#    happens, we should bump our major build number, because we may have broken someone.
import sys
from inspect import Parameter, signature

import pytest

from conda_build import api

pytestmark = pytest.mark.no_default_testing_config


def positional_parameters(func):
    return [
        (parameter.name, parameter.default)
        for parameter in signature(func).parameters.values()
        if parameter.kind
        in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
    ]


def test_api_config():
    assert hasattr(api, "Config")
    assert hasattr(api, "get_or_merge_config")


def test_api_get_or_merge_config():
    assert positional_parameters(api.get_or_merge_config) == [
        ("config", Parameter.empty),
        ("variant", None),
    ]


def test_api_render():
    assert positional_parameters(api.render) == [
        ("recipe_path", Parameter.empty),
        ("config", None),
        ("variants", None),
        ("permit_unsatisfiable_variants", True),
        ("finalize", True),
        ("bypass_env_check", False),
    ]


def test_api_output_yaml():
    assert positional_parameters(api.output_yaml) == [
        ("metadata", Parameter.empty),
        ("file_path", None),
        ("suppress_outputs", False),
    ]


def test_api_get_output_file_paths():
    assert positional_parameters(api.get_output_file_paths) == [
        ("recipe_path_or_metadata", Parameter.empty),
        ("no_download_source", False),
        ("config", None),
        ("variants", None),
    ]


def test_api_check():
    assert positional_parameters(api.check) == [
        ("recipe_path", Parameter.empty),
        ("no_download_source", False),
        ("config", None),
        ("variants", None),
    ]


def test_api_build():
    assert positional_parameters(api.build) == [
        ("recipe_paths_or_metadata", Parameter.empty),
        ("post", None),
        ("need_source_download", True),
        ("build_only", False),
        ("notest", False),
        ("config", None),
        ("variants", None),
        ("stats", None),
    ]


def test_api_test():
    assert positional_parameters(api.test) == [
        ("recipedir_or_package_or_metadata", Parameter.empty),
        ("move_broken", True),
        ("config", None),
        ("stats", None),
    ]


def test_api_list_skeletons():
    assert positional_parameters(api.list_skeletons) == []


def test_api_skeletonize():
    assert positional_parameters(api.skeletonize) == [
        ("packages", Parameter.empty),
        ("repo", Parameter.empty),
        ("output_dir", "."),
        ("version", None),
        ("recursive", False),
        ("config", None),
    ]


def test_api_develop():
    assert positional_parameters(api.develop) == [
        ("recipe_dir", Parameter.empty),
        ("prefix", sys.prefix),
        ("no_pth_file", False),
        ("build_ext", False),
        ("clean", False),
        ("uninstall", False),
    ]


def test_api_convert():
    assert positional_parameters(api.convert) == [
        ("package_file", Parameter.empty),
        ("output_dir", "."),
        ("show_imports", False),
        ("platforms", None),
        ("force", False),
        ("dependencies", None),
        ("verbose", False),
        ("quiet", True),
        ("dry_run", False),
    ]


def test_api_installable():
    assert positional_parameters(api.test_installable) == [
        ("channel", "defaults"),
    ]


def test_api_inspect_linkages():
    assert positional_parameters(api.inspect_linkages) == [
        ("packages", Parameter.empty),
        ("prefix", sys.prefix),
        ("untracked", False),
        ("all_packages", False),
        ("show_files", False),
        ("groupby", "package"),
        ("sysroot", ""),
    ]


def test_api_inspect_objects():
    assert positional_parameters(api.inspect_objects) == [
        ("packages", Parameter.empty),
        ("prefix", sys.prefix),
        ("groupby", "filename"),
    ]


def test_api_inspect_prefix_length():
    # hard-coded prefix length as intentional check here
    assert positional_parameters(api.inspect_prefix_length) == [
        ("packages", Parameter.empty),
        ("min_prefix_length", 255),
    ]


def test_api_create_metapackage():
    assert positional_parameters(api.create_metapackage) == [
        ("name", Parameter.empty),
        ("version", Parameter.empty),
        ("entry_points", ()),
        ("build_string", None),
        ("build_number", 0),
        ("dependencies", ()),
        ("home", None),
        ("license_name", None),
        ("summary", None),
        ("config", None),
    ]
