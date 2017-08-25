import os
import subprocess
import tarfile

import pytest

from conda_build import source
from conda_build.conda_interface import TemporaryDirectory
from conda_build.source import download_to_cache
from .utils import thisdir


def test_multiple_url_sources(testing_metadata):

    testing_metadata.meta['source'] = [
        {'folder': 'f1', 'url': os.path.join(thisdir, 'archives', 'a.tar.bz2')},
        {'folder': 'f2', 'url': os.path.join(thisdir, 'archives', 'b.tar.bz2')}]
    source.provide(testing_metadata)
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'f1'))
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'f2'))
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'f1', 'a'))
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'f2', 'b'))


def test_multiple_url_sources_into_same_folder(testing_metadata):
    testing_metadata.meta['source'] = [
        {'folder': 'f1', 'url': os.path.join(thisdir, 'archives', 'a.tar.bz2')},
        {'folder': 'f1', 'url': os.path.join(thisdir, 'archives', 'b.tar.bz2')}]
    source.provide(testing_metadata)
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'f1'))
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'f1', 'a'))
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'f1', 'b'))


def test_extract_tarball_with_subfolders_moves_files(testing_metadata):
    """Ensure that tarballs that contain only a single folder get their contents
    hoisted up one level"""
    testing_metadata.meta['source'] = {
        'url': os.path.join(thisdir, 'archives', 'subfolder.tar.bz2')}
    source.provide(testing_metadata)
    assert not os.path.exists(os.path.join(testing_metadata.config.work_dir, 'subfolder'))
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'abc'))


def test_extract_multiple_tarballs_with_subfolders_flattens_all(testing_metadata):
    """Ensure that tarballs that contain only a single folder get their contents
    hoisted up one level"""
    testing_metadata.meta['source'] = [
        {'folder': 'f1', 'url': os.path.join(thisdir, 'archives', 'subfolder.tar.bz2')},
        {'folder': 'f1', 'url': os.path.join(thisdir, 'archives', 'subfolder2.tar.bz2')}]
    source.provide(testing_metadata)
    assert not os.path.exists(os.path.join(testing_metadata.config.work_dir, 'subfolder'))
    assert not os.path.exists(os.path.join(testing_metadata.config.work_dir, 'subfolder2'))
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'f1', 'abc'))
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'f1', 'def'))


def test_multiple_different_sources(testing_metadata):
    testing_metadata.meta['source'] = [
        {'folder': 'f1', 'url': os.path.join(thisdir, 'archives', 'a.tar.bz2')},
        {'folder': 'f2', 'git_url': 'https://github.com/conda/conda_build_test_recipe'}]
    source.provide(testing_metadata)
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'f1', 'a'))
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'f2', 'README.md'))

    # Test get_value() indexing syntax.
    assert testing_metadata.get_value('source/url') == testing_metadata.meta['source'][0]['url']
    assert testing_metadata.get_value('source/0/url') == testing_metadata.meta['source'][0]['url']
    assert (testing_metadata.get_value('source/1/git_url') ==
            testing_metadata.meta['source'][1]['git_url'])


def test_git_into_existing_populated_folder_raises(testing_metadata):
    """Git will not clone into a non-empty folder.  This should raise an exception."""
    testing_metadata.meta['source'] = [
        {'folder': 'f1', 'url': os.path.join(thisdir, 'archives', 'a.tar.bz2')},
        {'folder': 'f1', 'git_url': 'https://github.com/conda/conda_build_test_recipe'}]
    with pytest.raises(subprocess.CalledProcessError):
        source.provide(testing_metadata)


def test_git_repo_with_single_subdir_does_not_enter_subdir(testing_metadata):
    """Regression test for https://github.com/conda/conda-build/issues/1910 """
    testing_metadata.meta['source'] = {
        'git_url': 'https://github.com/conda/conda_build_single_folder_test'}
    source.provide(testing_metadata)
    assert os.path.basename(testing_metadata.config.work_dir) != 'one_folder'


def test_source_user_expand(testing_workdir):
    with TemporaryDirectory(dir=os.path.expanduser('~')) as tmp:
        with TemporaryDirectory() as tbz_srcdir:
            file_txt = os.path.join(tbz_srcdir, "file.txt")
            with open(file_txt, 'w') as f:
                f.write("hello")
            tbz_name = os.path.join(tmp, "cb-test.tar.bz2")
            with tarfile.open(tbz_name, "w:bz2") as tar:
                tar.add(tbz_srcdir, arcname=os.path.sep)
            for prefix in ('~', 'file:///~'):
                source_dict = {"url": os.path.join(prefix, os.path.basename(tmp), "cb-test.tar.bz2")}
                with TemporaryDirectory() as tmp2:
                    download_to_cache(tmp2, '', source_dict)


def test_hoist_same_name(testing_workdir):
    testdir = os.path.join(testing_workdir, 'test', 'test')
    outer_dir = os.path.join(testing_workdir, 'test')
    os.makedirs(testdir)
    with open(os.path.join(testdir, 'somefile'), 'w') as f:
        f.write('weeeee')
    source.hoist_single_extracted_folder(outer_dir)
    assert os.path.isfile(os.path.join(outer_dir, 'somefile'))
    assert not os.path.isdir(testdir)


def test_hoist_different_name(testing_workdir):
    testdir = os.path.join(testing_workdir, 'test')
    os.makedirs(testdir)
    with open(os.path.join(testdir, 'somefile'), 'w') as f:
        f.write('weeeee')
    source.hoist_single_extracted_folder(testdir)
    assert os.path.isfile(os.path.join(testing_workdir, 'somefile'))
    assert not os.path.isdir(testdir)


def test_append_hash_to_fn(testing_metadata, caplog):
    relative_zip = 'testfn.zip'
    assert source.append_hash_to_fn(relative_zip, '123') == 'testfn_123.zip'
    relative_tar_gz = 'testfn.tar.gz'
    assert source.append_hash_to_fn(relative_tar_gz, '123') == 'testfn_123.tar.gz'
    absolute_zip = '/abc/testfn.zip'
    assert source.append_hash_to_fn(absolute_zip, '123') == '/abc/testfn_123.zip'
    absolute_tar_gz = '/abc/testfn.tar.gz'
    assert source.append_hash_to_fn(absolute_tar_gz, '123') == '/abc/testfn_123.tar.gz'
    absolute_win_zip = 'C:\\abc\\testfn.zip'
    assert source.append_hash_to_fn(absolute_win_zip, '123') == 'C:\\abc\\testfn_123.zip'
    absolute_win_tar_gz = 'C:\\abc\\testfn.tar.gz'
    assert source.append_hash_to_fn(absolute_win_tar_gz, '123') == 'C:\\abc\\testfn_123.tar.gz'

    testing_metadata.meta['source'] = [
        {'folder': 'f1', 'url': os.path.join(thisdir, 'archives', 'a.tar.bz2')}]
    source.provide(testing_metadata)
    # would be nice if this worked, but broken on Travis.  Works locally.  Catchlog 1.2.2
    # assert caplog.text.count('No hash (md5, sha1, sha256) provided.') == 1
