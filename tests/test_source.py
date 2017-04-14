import os
import subprocess

import pytest

from conda_build import source
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


def test_multiple_different_sources(testing_metadata):
    testing_metadata.meta['source'] = [
        {'folder': 'f1', 'url': os.path.join(thisdir, 'archives', 'a.tar.bz2')},
        {'folder': 'f2', 'git_url': 'https://github.com/conda/conda_build_test_recipe'}]
    source.provide(testing_metadata)
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'f1', 'a'))
    assert os.path.exists(os.path.join(testing_metadata.config.work_dir, 'f2', 'README.md'))


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
