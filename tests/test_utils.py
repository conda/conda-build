# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import filelock
import pytest
from pytest import MonkeyPatch

import conda_build.utils as utils
from conda_build.exceptions import BuildLockError


@pytest.mark.skipif(
    utils.on_win, reason="only unix has python version in site-packages path"
)
def test_get_site_packages():
    # https://github.com/conda/conda-build/issues/1055#issuecomment-250961576
    # crazy unreal python version that should show up in a second
    crazy_path = os.path.join("/dummy", "lib", "python8.2", "site-packages")
    site_packages = utils.get_site_packages("/dummy", "8.2")
    assert site_packages == crazy_path


def test_prepend_sys_path():
    path = sys.path[:]
    with utils.sys_path_prepended(sys.prefix):
        assert sys.path != path
        assert sys.path[1].startswith(sys.prefix)


def test_copy_source_tree(namespace_setup):
    dst = os.path.join(namespace_setup, "dest")
    utils.copy_into(os.path.join(namespace_setup, "namespace"), dst)
    assert os.path.isfile(os.path.join(dst, "package", "module.py"))


def test_merge_namespace_trees(namespace_setup):
    dep = Path(namespace_setup, "other_tree", "namespace", "package", "dependency.py")
    dep.parent.mkdir(parents=True, exist_ok=True)
    dep.touch()

    utils.copy_into(os.path.join(namespace_setup, "other_tree"), namespace_setup)
    assert os.path.isfile(
        os.path.join(namespace_setup, "namespace", "package", "module.py")
    )
    assert os.path.isfile(dep)


@pytest.fixture(scope="function")
def namespace_setup(testing_workdir: os.PathLike) -> os.PathLike:
    module = Path(testing_workdir, "namespace", "package", "module.py")
    module.parent.mkdir(parents=True, exist_ok=True)
    module.touch()
    return testing_workdir


@pytest.mark.sanity
def test_disallow_merge_conflicts(namespace_setup: os.PathLike):
    duplicate = Path(namespace_setup, "dupe", "namespace", "package", "module.py")
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.touch()

    with pytest.raises(IOError):
        utils.merge_tree(
            os.path.dirname(duplicate),
            os.path.join(namespace_setup, "namespace", "package"),
        )


@pytest.mark.sanity
def test_is_subdir(testing_workdir):
    assert not utils.is_subdir(testing_workdir, testing_workdir)
    assert utils.is_subdir(testing_workdir, testing_workdir, strict=False)
    subdir = os.path.join(testing_workdir, "subdir")
    assert utils.is_subdir(subdir, testing_workdir)
    assert utils.is_subdir(subdir, testing_workdir, strict=False)


@pytest.mark.sanity
def test_disallow_down_tree_merge(testing_workdir):
    src = testing_workdir
    with open(os.path.join(src, "testfile"), "w") as f:
        f.write("test")
    with pytest.raises(AssertionError):
        utils.merge_tree(src, testing_workdir)
    with pytest.raises(AssertionError):
        utils.merge_tree(src, os.path.join(testing_workdir, "subdir"))


@pytest.mark.sanity
def test_allow_up_tree_merge(testing_workdir):
    src = os.path.join(testing_workdir, "subdir")
    os.makedirs(src)
    with open(os.path.join(src, "testfile"), "w") as f:
        f.write("test")
    utils.merge_tree(src, testing_workdir)


def test_expand_globs(testing_workdir):
    sub_dir = os.path.join(testing_workdir, "sub1")
    os.mkdir(sub_dir)
    ssub_dir = os.path.join(sub_dir, "ssub1")
    os.mkdir(ssub_dir)
    files = [
        "abc",
        "acb",
        os.path.join(sub_dir, "def"),
        os.path.join(sub_dir, "abc"),
        os.path.join(ssub_dir, "ghi"),
        os.path.join(ssub_dir, "abc"),
    ]
    for f in files:
        with open(f, "w") as _f:
            _f.write("weee")

    # Test dirs
    exp = utils.expand_globs([os.path.join("sub1", "ssub1")], testing_workdir)
    assert sorted(exp) == sorted(
        [
            os.path.sep.join(("sub1", "ssub1", "ghi")),
            os.path.sep.join(("sub1", "ssub1", "abc")),
        ]
    )

    # Test files
    exp = sorted(utils.expand_globs(["abc", files[2]], testing_workdir))
    assert exp == sorted(["abc", os.path.sep.join(("sub1", "def"))])

    # Test globs
    exp = sorted(utils.expand_globs(["a*", "*/*f", "**/*i"], testing_workdir))
    assert exp == sorted(
        [
            "abc",
            "acb",
            os.path.sep.join(("sub1", "def")),
            os.path.sep.join(("sub1", "ssub1", "ghi")),
        ]
    )


def test_filter_files():
    # Files that should be filtered out.
    files_list = [
        ".git/a",
        "something/.git/a",
        ".git\\a",
        "something\\.git\\a",
        "file.la",
        "something/file.la",
        "python.exe.conda_trash",
        "bla.dll.conda_trash_1",
        "bla.dll.conda_trash.conda_trash",
    ]
    assert not utils.filter_files(files_list, "")

    # Files that should *not* be filtered out.
    # Example of valid 'x.git' directory:
    #    lib/python3.4/site-packages/craftr/stl/craftr.utils.git/Craftrfile
    files_list = [
        "a",
        "x.git/a",
        "something/x.git/a",
        "x.git\\a",
        "something\\x.git\\a",
        "something/.gitmodules",
        "some/template/directory/.gitignore",
        "another.lab",
        "miniconda_trashcan.py",
        "conda_trash_avoider.py",
    ]
    assert len(utils.filter_files(files_list, "")) == len(files_list)


@pytest.mark.serial
def test_logger_filtering(caplog, capfd):
    import logging

    log = utils.get_logger(__name__, level=logging.DEBUG)
    log.debug("test debug message")
    log.info("test info message")
    log.info("test duplicate message")
    log.info("test duplicate message")
    log.warning("test warn message")
    log.error("test error message")
    out, err = capfd.readouterr()
    assert "test debug message" in out
    assert "test info message" in out
    assert "test warn message" not in out
    assert "test error message" not in out
    assert "test debug message" not in err
    assert "test info message" not in err
    assert "test warn message" in err
    assert "test error message" in err
    assert caplog.text.count("duplicate") == 1
    log.removeHandler(logging.StreamHandler(sys.stdout))
    log.removeHandler(logging.StreamHandler(sys.stderr))


def test_logger_config_from_file(testing_workdir, capfd, mocker):
    test_file = os.path.join(testing_workdir, "build_log_config.yaml")
    with open(test_file, "w") as f:
        f.write(
            f"""
version: 1
formatters:
  simple:
    format: '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
handlers:
  console:
    class: logging.StreamHandler
    level: WARN
    formatter: simple
    stream: ext://sys.stdout
loggers:
  {__name__}:
    level: WARN
    handlers: [console]
    propagate: no
root:
  level: DEBUG
  handlers: [console]
"""
        )
    mocker.patch(
        "conda.base.context.Context.conda_build",
        new_callable=mocker.PropertyMock,
        return_value={"log_config_file": test_file},
    )
    log = utils.get_logger(__name__)
    # default log level is INFO, but our config file should set level to DEBUG
    log.warning("test message")
    # output should have gone to stdout according to config above.
    out, err = capfd.readouterr()
    assert "test message" in out
    # make sure that it is not in stderr - this is testing override of defaults.
    assert "test message" not in err


def test_ensure_valid_spec():
    assert utils.ensure_valid_spec("python") == "python"
    assert utils.ensure_valid_spec("python 3.8") == "python 3.8.*"
    assert utils.ensure_valid_spec("python 3.8.2") == "python 3.8.2.*"
    assert utils.ensure_valid_spec("python 3.8.10 0") == "python 3.8.10 0"
    assert utils.ensure_valid_spec("python >=3.8,<3.9") == "python >=3.8,<3.9"
    assert utils.ensure_valid_spec("numpy x.x") == "numpy x.x"
    assert utils.ensure_valid_spec(utils.MatchSpec("numpy x.x")) == utils.MatchSpec(
        "numpy x.x"
    )


def test_insert_variant_versions(testing_metadata):
    testing_metadata.meta["requirements"]["build"] = ["python", "numpy 1.13"]
    testing_metadata.config.variant = {"python": "3.8", "numpy": "1.11"}
    utils.insert_variant_versions(
        testing_metadata.meta.get("requirements", {}),
        testing_metadata.config.variant,
        "build",
    )
    # this one gets inserted
    assert "python 3.8.*" in testing_metadata.meta["requirements"]["build"]
    # this one should not be altered
    assert "numpy 1.13" in testing_metadata.meta["requirements"]["build"]
    # the overall length does not change
    assert len(testing_metadata.meta["requirements"]["build"]) == 2


def test_subprocess_stats_call(testing_workdir):
    stats = {}
    utils.check_call_env(["hostname"], stats=stats, cwd=testing_workdir)
    assert stats
    stats = {}
    out = utils.check_output_env(["hostname"], stats=stats, cwd=testing_workdir)
    assert out
    assert stats
    with pytest.raises(subprocess.CalledProcessError):
        utils.check_call_env(["bash", "-c", "exit 1"], cwd=testing_workdir)


def test_try_acquire_locks(testing_workdir):
    # Acquiring two unlocked locks should succeed.
    lock1 = filelock.FileLock(os.path.join(testing_workdir, "lock1"))
    lock2 = filelock.FileLock(os.path.join(testing_workdir, "lock2"))
    with utils.try_acquire_locks([lock1, lock2], timeout=1):
        pass

    # Acquiring the same lock twice should fail.
    lock1_copy = filelock.FileLock(os.path.join(testing_workdir, "lock1"))
    # Also verify that the error message contains the word "lock", since we rely
    # on this elsewhere.
    with pytest.raises(BuildLockError, match="Failed to acquire all locks"):
        with utils.try_acquire_locks([lock1, lock1_copy], timeout=1):
            pass


def test_get_lock(testing_workdir):
    lock1 = utils.get_lock(os.path.join(testing_workdir, "lock1"))
    lock2 = utils.get_lock(os.path.join(testing_workdir, "lock2"))

    # Different folders should get different lock files.
    assert lock1.lock_file != lock2.lock_file

    # Same folder should get the same lock file.
    lock1_copy = utils.get_lock(os.path.join(testing_workdir, "lock1"))
    assert lock1.lock_file == lock1_copy.lock_file

    # ...even when not normalized
    lock1_unnormalized = utils.get_lock(
        os.path.join(testing_workdir, "foo", "..", "lock1")
    )
    assert lock1.lock_file == lock1_unnormalized.lock_file


def test_rec_glob(tmp_path: Path):
    (dirA := tmp_path / "dirA").mkdir()
    (dirB := tmp_path / "dirB").mkdir()

    (path1 := dirA / "fileA").touch()
    (path2 := dirA / "fileB").touch()
    (path3 := dirB / "fileA").touch()
    (path4 := dirB / "fileB").touch()

    assert {str(path1), str(path3)} == set(utils.rec_glob(tmp_path, "fileA"))
    assert {str(path3), str(path4)} == set(
        utils.rec_glob(
            tmp_path,
            ("fileA", "fileB"),
            ignores="dirA",
        )
    )
    assert {str(path2)} == set(utils.rec_glob(tmp_path, "fileB", ignores=["dirB"]))


@pytest.mark.parametrize("file", ["meta.yaml", "meta.yml", "conda.yaml", "conda.yml"])
def test_find_recipe(tmp_path: Path, file: str):
    # check that each of these are valid recipes
    for path in (
        tmp_path / file,
        tmp_path / "dirA" / file,
        tmp_path / "dirA" / "dirB" / file,
        tmp_path / "dirA" / "dirC" / file,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        assert path.samefile(utils.find_recipe(tmp_path))
        path.unlink()


@pytest.mark.parametrize("file", ["meta.yaml", "meta.yml", "conda.yaml", "conda.yml"])
def test_find_recipe_relative(tmp_path: Path, monkeypatch: MonkeyPatch, file: str):
    (dirA := tmp_path / "dirA").mkdir()
    (path := dirA / file).touch()

    # check that even when given a relative recipe path we still return
    # the absolute path
    monkeypatch.chdir(tmp_path)
    assert path.samefile(utils.find_recipe("dirA"))


def test_find_recipe_no_meta(tmp_path: Path):
    # no recipe in tmp_path
    with pytest.raises(IOError):
        utils.find_recipe(tmp_path)


def test_find_recipe_file(tmp_path: Path):
    # provided recipe is valid
    (path := tmp_path / "meta.yaml").touch()
    assert path.samefile(utils.find_recipe(path))


def test_find_recipe_file_bad(tmp_path: Path):
    # missing recipe is invalid
    path = tmp_path / "not_a_recipe"
    with pytest.raises(IOError):
        utils.find_recipe(path)

    # provided recipe is invalid
    path.touch()
    with pytest.raises(IOError):
        utils.find_recipe(path)


@pytest.mark.parametrize("file", ["meta.yaml", "meta.yml", "conda.yaml", "conda.yml"])
def test_find_recipe_multipe_base(tmp_path: Path, file: str):
    (dirA := tmp_path / "dirA").mkdir()
    (dirB := dirA / "dirB").mkdir()
    (dirC := dirA / "dirC").mkdir()

    (path1 := tmp_path / file).touch()
    (dirA / file).touch()
    (dirB / file).touch()
    (dirC / file).touch()

    # multiple recipe, use the one at the top level
    assert path1.samefile(utils.find_recipe(tmp_path))


@pytest.mark.parametrize("stem", ["meta", "conda"])
def test_find_recipe_multipe_bad(tmp_path: Path, stem: str):
    (dirA := tmp_path / "dirA").mkdir()
    (dirB := dirA / "dirB").mkdir()
    (dirC := dirA / "dirC").mkdir()

    # create multiple nested recipes at the same depth
    (dirB / f"{stem}.yml").touch()
    (dirC / f"{stem}.yaml").touch()

    # too many equal priority recipes found
    with pytest.raises(IOError):
        utils.find_recipe(tmp_path)

    # create multiple recipes at the top level
    (tmp_path / f"{stem}.yml").touch()
    (tmp_path / f"{stem}.yaml").touch()

    # too many recipes in the top level
    with pytest.raises(IOError):
        utils.find_recipe(tmp_path)


class IsCondaPkgTestData(NamedTuple):
    value: str
    expected: bool
    is_dir: bool
    create: bool


IS_CONDA_PKG_DATA = (
    IsCondaPkgTestData(
        value="aws-c-common-0.4.57-hb1e8313_1.tar.bz2",
        expected=True,
        is_dir=False,
        create=True,
    ),
    IsCondaPkgTestData(
        value="aws-c-common-0.4.57-hb1e8313_1.tar.bz2",
        expected=False,
        is_dir=False,
        create=False,
    ),
    IsCondaPkgTestData(value="somedir", expected=False, is_dir=True, create=False),
)


@pytest.mark.parametrize("value,expected,is_dir,create", IS_CONDA_PKG_DATA)
def test_is_conda_pkg(tmpdir, value: str, expected: bool, is_dir: bool, create: bool):
    if create:
        value = os.path.join(tmpdir, value)
        if is_dir:
            os.mkdir(value)
        else:
            with open(value, "w") as fp:
                fp.write("test")

    assert utils.is_conda_pkg(value) == expected


def test_prefix_files(tmp_path: Path):
    # all files within the prefix are found
    (prefix := tmp_path / "prefix1").mkdir()
    (file1 := prefix / "file1").touch()
    (dirA := prefix / "dirA").mkdir()
    (file2 := dirA / "file2").touch()
    (dirB := prefix / "dirB").mkdir()
    (file3 := dirB / "file3").touch()

    # files outside of the prefix are not found
    (prefix2 := tmp_path / "prefix2").mkdir()
    (prefix2 / "file4").touch()
    (dirC := prefix2 / "dirC").mkdir()
    (dirC / "file5").touch()

    # even if they are symlinked
    (link1 := prefix / "dirC").symlink_to(dirC)

    paths = {str(path.relative_to(prefix)) for path in (file1, file2, file3, link1)}
    assert paths == utils.prefix_files(str(prefix))
