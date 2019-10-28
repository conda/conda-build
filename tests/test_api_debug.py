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

from .utils import metadata_dir, thisdir, on_win

recipe_path = os.path.join(metadata_dir, "_debug_pkg")
ambiguous_recipe_path = os.path.join(metadata_dir, "_debug_pkg_multiple_outputs")
tarball_path = os.path.join(thisdir, "archives", "test_debug_pkg-1.0-0.tar.bz2")

if on_win:
    shell_cmd = ["cmd.exe", "/d", "/c"]
else:
    shell_cmd = ["bash", "-c"]


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


@pytest.mark.slow
def test_debug_recipe_default_path(testing_config):
    activation_string = api.debug(recipe_path, config=testing_config)
    assert activation_string and "debug_1" in activation_string
    _, work_dir, _, src_command, env_activation_script = activation_string.split()
    _shell_cmd = shell_cmd + [' '.join((src_command, env_activation_script))]
    subprocess.check_call(_shell_cmd, cwd=work_dir)
    check_build_files_present(work_dir, True)
    check_test_files_present(work_dir, False)
    assert_correct_folders(work_dir)


@pytest.mark.skipif(
    utils.on_win and sys.version_info <= (3, 4),
    reason="Skipping on windows and vc<14"
)
def test_debug_package_default_path(testing_config):
    activation_string = api.debug(tarball_path, config=testing_config)
    _, work_dir, _, src_command, env_activation_script = activation_string.split()
    _shell_cmd = shell_cmd + [' '.join((src_command, env_activation_script))]
    subprocess.check_call(_shell_cmd, cwd=work_dir)
    check_build_files_present(work_dir, False)
    check_test_files_present(work_dir, True)
    assert_correct_folders(work_dir, build=False)


@pytest.mark.slow
def test_debug_recipe_custom_path(testing_workdir):
    activation_string = api.debug(recipe_path, path=testing_workdir)
    assert activation_string and "debug_1" not in activation_string
    _, work_dir, _, src_command, env_activation_script = activation_string.split()
    _shell_cmd = shell_cmd + [' '.join((src_command, env_activation_script))]
    subprocess.check_call(_shell_cmd, cwd=work_dir)
    check_build_files_present(work_dir, True)
    check_test_files_present(work_dir, False)
    assert_correct_folders(work_dir)


def test_debug_package_custom_path(testing_workdir):
    activation_string = api.debug(tarball_path, path=testing_workdir)
    _, work_dir, _, src_command, env_activation_script = activation_string.split()
    _shell_cmd = shell_cmd + [' '.join((src_command, env_activation_script))]
    subprocess.check_call(_shell_cmd, cwd=work_dir)
    check_build_files_present(work_dir, False)
    check_test_files_present(work_dir, True)
    assert_correct_folders(work_dir, build=False)


def test_specific_output():
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
