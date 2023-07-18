# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import sys

import pytest

from conda_build.conda_interface import TemporaryDirectory
from conda_build.config import Config, get_or_merge_config
from conda_build.utils import on_win


@pytest.fixture
def config():
    """a tiny bit of a fixture to save us from manually creating a new Config each test"""
    return Config()


@pytest.fixture
def build_id():
    """Small support fixture for setting build id's in multiple builds which may need them"""
    return "test123"


def test_set_build_id(config, build_id):
    config.build_id = build_id
    # windows always uses the short prefix due to its limitation of 260 char paths
    if sys.platform == "win32":
        assert config.host_prefix == os.path.join(config.croot, build_id, "_h_env")
    else:
        long_prefix = os.path.join(
            config.croot, build_id, "_h_env" + "_placehold" * 25
        )[: config.prefix_length]
        assert config.host_prefix == long_prefix


def test_keep_old_work(config, build_id):
    config.keep_old_work = True
    with TemporaryDirectory() as temp_dir:
        config.croot = temp_dir
        config.build_id = build_id
        work_path = os.path.join(temp_dir, build_id, "work")
        os.makedirs(work_path)
        # assert False
        assert len(os.listdir(config.work_dir)) == 0
        with open(os.path.join(work_path, "a_touched_file.magic"), "w") as _:
            # Touch a random file so the "work_dir" is not empty
            pass
        assert len(os.listdir(config.work_dir)) > 0
        config.compute_build_id("a_new_name", reset=True)
        assert config.work_dir != work_path
        assert not os.path.exists(work_path)
        assert len(os.listdir(config.work_dir)) > 0


@pytest.mark.skipif(on_win, reason="Windows uses only the short prefix")
def test_long_build_prefix_length(config):
    config.use_long_build_prefix = True
    config.prefix_length = 80
    assert len(config.host_prefix) == config.prefix_length
    config.prefix_length = 255
    assert len(config.host_prefix) == config.prefix_length


@pytest.mark.skipif(on_win, reason="Windows uses only the short prefix")
def test_long_test_prefix_length(config):
    # defaults to True in conda-build 3.0+
    assert config.long_test_prefix
    assert "_plac" in config.test_prefix
    config.long_test_prefix = True
    # The length of the testing prefix is reduced by 2 characters to check if the null
    # byte padding causes issues
    config.prefix_length = 80
    assert len(config.test_prefix) == config.prefix_length - 2
    config.prefix_length = 255
    assert len(config.test_prefix) == config.prefix_length - 2


def test_build_id_at_end_of_long_build_prefix(config, build_id):
    config.build_id = build_id
    assert build_id in config.host_prefix


def test_create_config_with_subdir():
    config = Config(host_subdir="steve-128")
    assert config.host_platform == "steve"
    assert config.host_subdir == "steve-128"


def test_set_platform(config):
    config.host_platform = "steve"
    arch = config.arch
    assert config.host_subdir == "steve-" + str(arch)


def test_set_subdir(config):
    config.host_subdir = "steve"
    arch = config.arch
    assert config.host_subdir == "steve-" + str(arch)
    assert config.host_platform == "steve"

    config.host_subdir = "steve-128"
    assert config.host_subdir == "steve-128"
    assert config.host_platform == "steve"
    assert config.host_arch == "128"


def test_set_bits(config):
    config.host_arch = 128
    assert config.host_subdir == config.platform + "-" + str(128)
    assert config.host_arch == 128


def test_get_or_create_config_does_not_change_passed_in_config(config):
    # arguments merged into existing configs should only affect new config, not the one that
    #    was passed in
    assert config.dirty is False
    newconfig = get_or_merge_config(config, dirty=True)
    assert newconfig.dirty is True
    assert config.dirty is False
