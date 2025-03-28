# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import json
import logging
import os
import shutil
import sys
from pathlib import Path

import pytest

import conda_build.utils
from conda_build import api, post
from conda_build.utils import (
    get_site_packages,
    on_linux,
    on_mac,
    on_win,
    package_has_file,
)

from .utils import add_mangling, metadata_dir, subpackage_path


@pytest.mark.skipif(
    sys.version_info >= (3, 10),
    reason="Python 3.10+, py_compile terminates once it finds an invalid file",
)
def test_compile_missing_pyc(testing_workdir):
    good_files = ["f1.py", "f3.py"]
    bad_file = "f2_bad.py"
    tmp = os.path.join(testing_workdir, "tmp")
    shutil.copytree(
        os.path.join(
            os.path.dirname(__file__), "test-recipes", "metadata", "_compile-test"
        ),
        tmp,
    )
    post.compile_missing_pyc(os.listdir(tmp), cwd=tmp, python_exe=sys.executable)
    for f in good_files:
        assert os.path.isfile(os.path.join(tmp, add_mangling(f)))
    assert not os.path.isfile(os.path.join(tmp, add_mangling(bad_file)))


def test_hardlinks_to_copies():
    with open("test1", "w") as f:
        f.write("\n")

    os.link("test1", "test2")
    assert os.lstat("test1").st_nlink == 2
    assert os.lstat("test2").st_nlink == 2

    post.make_hardlink_copy("test1", os.getcwd())
    post.make_hardlink_copy("test2", os.getcwd())

    assert os.lstat("test1").st_nlink == 1
    assert os.lstat("test2").st_nlink == 1


def test_postbuild_files_raise(testing_metadata):
    fn = "buildstr", "buildnum", "version"
    for f in fn:
        with open(
            os.path.join(testing_metadata.config.work_dir, f"__conda_{f}__.txt"), "w"
        ) as fh:
            fh.write("123")
        with pytest.raises(ValueError, match=f):
            post.get_build_metadata(testing_metadata)


@pytest.mark.skipif(on_win, reason="fix_shebang is not executed on win32")
def test_fix_shebang():
    fname = "test1"
    with open(fname, "w") as f:
        f.write("\n")
    os.chmod(fname, 0o000)
    post.fix_shebang(fname, ".", "/test/python")
    assert (os.stat(fname).st_mode & 0o777) == 0o775


def test_postlink_script_in_output_explicit(testing_config):
    recipe = os.path.join(metadata_dir, "_post_link_in_output")
    pkg = api.build(recipe, config=testing_config, notest=True)[0]
    assert package_has_file(pkg, "bin/.out1-post-link.sh") or package_has_file(
        pkg, "Scripts/.out1-post-link.bat"
    )


def test_postlink_script_in_output_implicit(testing_config):
    recipe = os.path.join(metadata_dir, "_post_link_in_output_implicit")
    pkg = api.build(recipe, config=testing_config, notest=True)[0]
    assert package_has_file(pkg, "bin/.out1-post-link.sh") or package_has_file(
        pkg, "Scripts/.out1-post-link.bat"
    )


def test_pypi_installer_metadata(testing_config):
    recipe = os.path.join(metadata_dir, "_pypi_installer_metadata")
    pkg = api.build(recipe, config=testing_config, notest=True)[0]
    expected_installer = "{}/imagesize-1.1.0.dist-info/INSTALLER".format(
        get_site_packages("", "3.9")
    )
    assert "conda" == (package_has_file(pkg, expected_installer, refresh_mode="forced"))


def test_menuinst_validation_ok(testing_config, caplog, tmp_path):
    "1st check - validation passes with recipe as is"
    recipe = Path(metadata_dir, "_menu_json_validation")
    recipe_tmp = tmp_path / "_menu_json_validation"
    shutil.copytree(recipe, recipe_tmp)

    with caplog.at_level(logging.INFO):
        pkg = api.build(str(recipe_tmp), config=testing_config, notest=True)[0]

    captured_text = caplog.text
    assert "Found 'Menu/*.json' files but couldn't validate:" not in captured_text
    assert "not a valid menuinst JSON file" not in captured_text
    assert "is a valid menuinst JSON document" in captured_text
    assert package_has_file(pkg, "Menu/menu_json_validation.json")


def test_menuinst_validation_fails_bad_schema(testing_config, caplog, tmp_path):
    "2nd check - valid JSON but invalid content fails validation"
    recipe = Path(metadata_dir, "_menu_json_validation")
    recipe_tmp = tmp_path / "_menu_json_validation"
    shutil.copytree(recipe, recipe_tmp)
    menu_json = recipe_tmp / "menu.json"
    menu_json_contents = menu_json.read_text()

    bad_data = json.loads(menu_json_contents)
    bad_data["menu_items"][0]["osx"] = ["bad", "schema"]
    menu_json.write_text(json.dumps(bad_data, indent=2))
    with caplog.at_level(logging.WARNING):
        api.build(str(recipe_tmp), config=testing_config, notest=True)

    captured_text = caplog.text
    assert "Found 'Menu/*.json' files but couldn't validate:" not in captured_text
    assert "not a valid menuinst JSON document" in captured_text
    assert "ValidationError" in captured_text


def test_menuinst_validation_fails_bad_json(testing_config, monkeypatch, tmp_path):
    "3rd check - non-parsable JSON fails validation"
    recipe = Path(metadata_dir, "_menu_json_validation")
    recipe_tmp = tmp_path / "_menu_json_validation"
    shutil.copytree(recipe, recipe_tmp)
    menu_json = recipe_tmp / "menu.json"
    menu_json_contents = menu_json.read_text()
    menu_json.write_text(menu_json_contents + "Make this an invalid JSON")

    # suspect caplog fixture may fail; use monkeypatch instead.
    records = []

    class MonkeyLogger:
        def __getattr__(self, name):
            return self.warning

        def warning(self, *args, **kwargs):
            records.append((*args, kwargs))

    monkeylogger = MonkeyLogger()

    def get_monkey_logger(*args, **kwargs):
        return monkeylogger

    # For some reason it uses get_logger in the individual functions, instead of
    # a module-level global that we could easily patch.
    monkeypatch.setattr(conda_build.utils, "get_logger", get_monkey_logger)

    api.build(str(recipe_tmp), config=testing_config, notest=True)

    # without %s substitution
    messages = [record[0] for record in records]

    assert "Found 'Menu/*.json' files but couldn't validate: %s" not in messages
    assert "'%s' is not a valid menuinst JSON document!" in messages
    assert any(
        isinstance(record[-1].get("exc_info"), json.JSONDecodeError)
        for record in records
    )


def test_file_hash(testing_config, caplog, tmp_path):
    "check that the post-link check caching takes the file path into consideration"
    recipe = Path(subpackage_path, "_test-file-hash")
    recipe_tmp = tmp_path / "test-file-hash"
    shutil.copytree(recipe, recipe_tmp)

    variants = {"python": ["3.11", "3.12"]}
    testing_config.ignore_system_config = True
    testing_config.activate = True

    with caplog.at_level(logging.INFO):
        api.build(
            str(recipe_tmp),
            config=testing_config,
            notest=True,
            variants=variants,
            activate=True,
        )


@pytest.mark.skipif(on_win, reason="rpath fixup not done on Windows.")
def test_rpath_symlink(mocker, testing_config):
    if on_linux:
        mk_relative = mocker.spy(post, "mk_relative_linux")
    elif on_mac:
        mk_relative = mocker.spy(post, "mk_relative_osx")
    api.build(
        os.path.join(metadata_dir, "_rpath_symlink"),
        config=testing_config,
        variants={"rpaths_patcher": ["patchelf", "LIEF"]},
        activate=True,
    )
    # Should only be called on the actual binary, not its symlinks. (once per variant)
    assert mk_relative.call_count == 2
