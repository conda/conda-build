# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
This module tests the test API.  These are high-level integration tests.  Lower level unit tests
should go in test_render.py
"""

import os
from glob import glob

import pytest
import subprocess

import sys

from conda_build import api
from tests import utils

from .utils import (
    recipe_path,
    ambiguous_recipe_path,
    tarball_path,
    assert_correct_folders,
    check_build_files_present,
    check_test_files_present,
    switch_between_shell_and_bash)

@pytest.mark.sanity
def test_debug_recipe_default_path(testing_config, shell_cmd=switch_between_shell_and_bash()):
    activation_string = api.debug(recipe_path, config=testing_config)
    assert activation_string and "debug_1" in activation_string
    _, work_dir, _, src_command, env_activation_script = activation_string.split()
    _shell_cmd = shell_cmd + [' '.join((src_command, env_activation_script))]
    subprocess.check_call(_shell_cmd, cwd=work_dir)
    check_build_files_present(work_dir, True)
    check_test_files_present(work_dir, False)
    assert_correct_folders(work_dir)

@pytest.mark.sanity
@pytest.mark.skipif(
    utils.on_win and sys.version_info <= (3, 4),
    reason="Skipping on windows and vc<14"
)
def test_debug_package_default_path(testing_config, shell_cmd=switch_between_shell_and_bash()):
    activation_string = api.debug(tarball_path, config=testing_config)
    _, work_dir, _, src_command, env_activation_script = activation_string.split()
    _shell_cmd = shell_cmd + [' '.join((src_command, env_activation_script))]
    subprocess.check_call(_shell_cmd, cwd=work_dir)
    check_build_files_present(work_dir, False)
    check_test_files_present(work_dir, True)
    assert_correct_folders(work_dir, build=False)


def test_debug_recipe_custom_path(testing_workdir, shell_cmd=switch_between_shell_and_bash()):
    activation_string = api.debug(recipe_path, path=testing_workdir)
    assert activation_string and "debug_1" not in activation_string
    _, work_dir, _, src_command, env_activation_script = activation_string.split()
    _shell_cmd = shell_cmd + [' '.join((src_command, env_activation_script))]
    subprocess.check_call(_shell_cmd, cwd=work_dir)
    check_build_files_present(work_dir, True)
    check_test_files_present(work_dir, False)
    assert_correct_folders(work_dir)


def test_debug_package_custom_path(testing_workdir, shell_cmd=switch_between_shell_and_bash()):
    activation_string = api.debug(tarball_path, path=testing_workdir)
    _, work_dir, _, src_command, env_activation_script = activation_string.split()
    _shell_cmd = shell_cmd + [' '.join((src_command, env_activation_script))]
    subprocess.check_call(_shell_cmd, cwd=work_dir)
    check_build_files_present(work_dir, False)
    check_test_files_present(work_dir, True)
    assert_correct_folders(work_dir, build=False)


def test_specific_output(shell_cmd=switch_between_shell_and_bash()):
    activation_string = api.debug(ambiguous_recipe_path, output_id="output1*")
    _, work_dir, _, src_command, env_activation_script = activation_string.split()
    _shell_cmd = shell_cmd + [' '.join((src_command, env_activation_script))]
    subprocess.check_call(_shell_cmd, cwd=work_dir)
    check_build_files_present(work_dir, True)
    check_test_files_present(work_dir, False)
    assert_correct_folders(work_dir, build=True)


@pytest.mark.sanity
def test_error_on_ambiguous_output():
    with pytest.raises(ValueError):
        api.debug(ambiguous_recipe_path)


@pytest.mark.sanity
def test_error_on_unmatched_output():
    with pytest.raises(ValueError):
        api.debug(ambiguous_recipe_path, output_id="frank")
