"""
This file tests the build.py module.  It sits lower in the stack than the API tests,
and is more unit-test oriented.
"""

import json
import os
import subprocess
import sys

import pytest

import conda
from conda_build import build, api, __version__
from conda_build.metadata import MetaData
from conda_build.utils import rm_rf, on_win

from .utils import (testing_workdir, test_config, test_metadata, metadata_dir,
                    get_noarch_python_meta, put_bad_conda_on_path)

prefix_tests = {"normal": os.path.sep}
if sys.platform == "win32":
    prefix_tests.update({"double_backslash": "\\\\",
                         "forward_slash": "/"})


def _write_prefix(filename, prefix, replacement):
    with open(filename, "w") as f:
        f.write(prefix.replace(os.path.sep, replacement))
        f.write("\n")


def test_find_prefix_files(testing_workdir):
    """
    Write test output that has the prefix to be found, then verify that the prefix finding
    identified the correct number of files.
    """
    # create text files to be replaced
    files = []
    for slash_style in prefix_tests:
        filename = os.path.join(testing_workdir, "%s.txt" % slash_style)
        _write_prefix(filename, testing_workdir, prefix_tests[slash_style])
        files.append(filename)

    assert len(list(build.have_prefix_files(files, testing_workdir))) == len(files)


def test_environment_creation_preserves_PATH(testing_workdir, test_config):
    ref_path = os.environ['PATH']
    build.create_env(testing_workdir, ['python'], test_config)
    assert os.environ['PATH'] == ref_path


def test_build_preserves_PATH(testing_workdir, test_config):
    m = MetaData(os.path.join(metadata_dir, 'source_git'), config=test_config)
    ref_path = os.environ['PATH']
    build.build(m, test_config)
    assert os.environ['PATH'] == ref_path


@pytest.mark.skipif(on_win, reason=("Windows binary prefix replacement (for pip exes)"
                                    " not length dependent"))
def test_env_creation_with_short_prefix_does_not_deadlock(caplog):
    test_base = os.path.expanduser("~/cbtmp")
    config = api.Config(croot=test_base, anaconda_upload=False, verbose=True)
    recipe_path = os.path.join(metadata_dir, "has_prefix_files")
    metadata, _, _ = api.render(recipe_path, config=config)
    metadata.meta['package']['name'] = 'test_env_creation_with_short_prefix'
    fn = api.get_output_file_path(metadata)
    if os.path.isfile(fn):
        os.remove(fn)
    config.prefix_length = 80
    try:
        api.build(metadata)
        pkg_name = os.path.basename(fn).replace("-1.0-0.tar.bz2", "")
        assert not api.inspect_prefix_length(fn, 255)
        config.prefix_length = 255
        build.create_env(config.build_prefix, specs=["python", pkg_name], config=config)
    except:
        raise
    finally:
        rm_rf(test_base)
    assert 'One or more of your package dependencies needs to be rebuilt' in caplog.text()


@pytest.mark.skipif(on_win, reason=("Windows binary prefix replacement (for pip exes)"
                                    " not length dependent"))
def test_catch_openssl_legacy_short_prefix_error(test_metadata, caplog):
    config = api.Config(anaconda_upload=False, verbose=True, python="2.6")
    test_metadata.config = api.get_or_merge_config(test_metadata.config, python='2.6')
    cmd = """
import os

prefix = os.environ['PREFIX']
fn = os.path.join(prefix, 'binary-has-prefix')

with open(fn, 'wb') as f:
    f.write(prefix.encode('utf-8') + b'\x00\x00')
 """
    test_metadata.meta['build']['script'] = 'python -c "{0}"'.format(cmd)

    api.build(test_metadata)
    assert "Falling back to legacy prefix" in caplog.text()


def test_warn_on_old_conda_build(test_config, capfd):
    installed_version = "1.21.14"

    # test with a conda-generated index first.  This is a list of Package objects,
    #    from which we just take the versions.
    build.update_index(test_config.croot, test_config)
    build.update_index(os.path.join(test_config.croot, test_config.subdir), test_config)
    build.update_index(os.path.join(test_config.croot, 'noarch'), test_config)
    index = build.get_build_index(test_config)
    # exercise the index code path, but this test is not at all deterministic.
    build.warn_on_old_conda_build(index=index)
    output, error = capfd.readouterr()

    # should see output here
    build.warn_on_old_conda_build(installed_version=installed_version,
                                  available_packages=['1.21.10', '2.0.0'])
    output, error = capfd.readouterr()
    assert "conda-build appears to be out of date. You have version " in error

    # should not see output here, because newer version has a beta tag
    build.warn_on_old_conda_build(installed_version=installed_version,
                                  available_packages=['1.21.10', '2.0.0beta2'])
    output, error = capfd.readouterr()
    assert "conda-build appears to be out of date. You have version " not in error

    # should not see output here, because newer version has a beta tag
    build.warn_on_old_conda_build(installed_version=installed_version,
                                  available_packages=['1.21.10', '2.0.0beta2'])
    output, error = capfd.readouterr()
    assert "conda-build appears to be out of date. You have version " not in error

    # should not barf on empty lists of packages; just not show anything
    #     entries with beta will be filtered out, leaving an empty list
    build.warn_on_old_conda_build(installed_version=installed_version,
                                  available_packages=['1.0.0beta'])
    output, error = capfd.readouterr()
    assert "conda-build appears to be out of date. You have version " not in error


def test_sanitize_channel():
    test_url = 'https://conda.anaconda.org/t/ms-534991f2-4123-473a-b512-42025291b927/somechannel'
    assert build.sanitize_channel(test_url) == 'https://conda.anaconda.org/t/<TOKEN>/somechannel'


def test_write_about_json_without_conda_on_path(testing_workdir, test_metadata):
    with put_bad_conda_on_path(testing_workdir):
        # verify that the correct (bad) conda is the one we call
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_output('conda -h', env=os.environ, shell=True)
        build.write_about_json(test_metadata, test_metadata.config)

    output_file = os.path.join(test_metadata.config.info_dir, 'about.json')
    assert os.path.isfile(output_file)
    with open(output_file) as f:
        about = json.load(f)
    assert 'conda_version' in about
    assert 'conda_build_version' in about


def test_get_short_path(test_metadata):
    # Test for regular package
    assert build.get_short_path(test_metadata, "test/file") == "test/file"

    # Test for noarch: python
    meta = get_noarch_python_meta(test_metadata)
    assert build.get_short_path(meta, "lib/site-packages/test") == "site-packages/test"
    assert build.get_short_path(meta, "bin/test") == "python-scripts/test"
    assert build.get_short_path(meta, "Scripts/test") == "python-scripts/test"


def test_has_prefix():
    files_with_prefix = [("prefix/path", "text", "short/path/1"),
                         ("prefix/path", "text", "short/path/2")]
    assert build.has_prefix("short/path/1", files_with_prefix) == ("prefix/path", "text")
    assert build.has_prefix("short/path/nope", files_with_prefix) == (None, None)


def test_is_no_link():
    no_link = ["path/1", "path/2"]
    assert build.is_no_link(no_link, "path/1") is True
    assert build.is_no_link(no_link, "path/nope") is None


@pytest.mark.skipif(on_win and sys.version[:3] == "2.7",
                    reason="os.link is not available so can't setup test")
def test_sorted_inode_first_path(testing_workdir):
    path_one = os.path.join(testing_workdir, "one")
    path_two = os.path.join(testing_workdir, "two")
    path_one_hardlink = os.path.join(testing_workdir, "one_hl")
    open(path_one, "a").close()
    open(path_two, "a").close()

    os.link(path_one, path_one_hardlink)

    files = ["one", "two", "one_hl"]
    assert build.get_inode_paths(files, "one", testing_workdir) == ["one", "one_hl"]
    assert build.get_inode_paths(files, "one_hl", testing_workdir) == ["one", "one_hl"]
    assert build.get_inode_paths(files, "two", testing_workdir) == ["two"]


def test_create_info_files_json(testing_workdir, test_metadata):
    info_dir = os.path.join(testing_workdir, "info")
    os.mkdir(info_dir)
    path_one = os.path.join(testing_workdir, "one")
    path_two = os.path.join(testing_workdir, "two")
    path_foo = os.path.join(testing_workdir, "foo")
    open(path_one, "a").close()
    open(path_two, "a").close()
    open(path_foo, "a").close()
    files_with_prefix = [("prefix/path", "text", "foo")]
    files = ["one", "two", "foo"]

    build.create_info_files_json(test_metadata, info_dir, testing_workdir, files, files_with_prefix)
    files_json_path = os.path.join(info_dir, "files.json")
    expected_output = {
        "files": [{"file_type": "hardlink", "short_path": "one",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0},
                  {"file_type": "hardlink", "short_path": "two", "size_in_bytes": 0,
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
                  {"file_mode": "text", "file_type": "hardlink",
                   "short_path": "foo", "prefix_placeholder": "prefix/path",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0}],
        "fields": ["short_path", "sha256", "size_in_bytes", "file_type", "file_mode",
                   "prefix_placeholder", "no_link", "inode_first_path"],
        "version": 1}
    with open(files_json_path, "r") as files_json:
        output = json.load(files_json)
        assert output == expected_output


@pytest.mark.skipif(on_win and sys.version[:3] == "2.7",
                    reason="os.link is not available so can't setup test")
def test_create_info_files_json_no_inodes(testing_workdir, test_metadata):
    info_dir = os.path.join(testing_workdir, "info")
    os.mkdir(info_dir)
    path_one = os.path.join(testing_workdir, "one")
    path_two = os.path.join(testing_workdir, "two")
    path_foo = os.path.join(testing_workdir, "foo")
    path_one_hardlink = os.path.join(testing_workdir, "one_hl")
    open(path_one, "a").close()
    open(path_two, "a").close()
    open(path_foo, "a").close()
    os.link(path_one, path_one_hardlink)
    files_with_prefix = [("prefix/path", "text", "foo")]
    files = ["one", "two", "one_hl", "foo"]

    build.create_info_files_json(test_metadata, info_dir, testing_workdir, files, files_with_prefix)
    files_json_path = os.path.join(info_dir, "files.json")
    expected_output = {
        "files": [{"inode_paths": ["one", "one_hl"], "file_type": "hardlink", "short_path": "one",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0},
                  {"file_type": "hardlink", "short_path": "two", "size_in_bytes": 0,
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
                  {"inode_paths": ["one", "one_hl"], "file_type": "hardlink",
                   "short_path": "one_hl",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0},
                  {"file_mode": "text", "file_type": "hardlink", "short_path": "foo",
                   "prefix_placeholder": "prefix/path",
                   "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                   "size_in_bytes": 0}],
        "fields": ["short_path", "sha256", "size_in_bytes", "file_type", "file_mode",
                   "prefix_placeholder", "no_link", "inode_first_path"],
        "version": 1}
    with open(files_json_path, "r") as files_json:
        assert json.load(files_json) == expected_output
