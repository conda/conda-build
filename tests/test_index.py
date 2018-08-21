# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

from contextlib import contextmanager
import json
from logging import getLogger
import os
from os.path import dirname, isdir, join, lexists, isfile
import requests
import shutil
from tempfile import gettempdir
from uuid import uuid4

from conda_build.conda_interface import rm_rf
from conda_build.index import update_index

log = getLogger(__name__)

# NOTE: The recipes for test packages used in this module are at https://github.com/kalefranz/conda-test-packages


def create_temp_location():
    tempdirdir = gettempdir()
    dirname = str(uuid4())[:8]
    return join(tempdirdir, dirname)


@contextmanager
def tempdir():
    prefix = create_temp_location()
    try:
        os.makedirs(prefix)
        yield prefix
    finally:
        if lexists(prefix):
            rm_rf(prefix)


def download(url, local_path):
    # NOTE: The tests in this module download packages from the conda-test channel.
    #       These packages are small, and could easily be included in the conda-build git
    #       repository once their use stabilizes.
    if not isdir(dirname(local_path)):
        os.makedirs(dirname(local_path))
    r = requests.get(url, stream=True)
    with open(local_path, 'wb') as f:
        shutil.copyfileobj(r.raw, f)
    return local_path


def test_index_on_single_subdir_1():
    with tempdir() as base_location:
        test_package_path = join(base_location, 'osx-64', 'conda-index-pkg-a-1.0-py27h5e241af_0.tar.bz2')
        test_package_url = 'https://conda.anaconda.org/conda-test/osx-64/conda-index-pkg-a-1.0-py27h5e241af_0.tar.bz2'
        download(test_package_url, test_package_path)

        update_index(base_location, channel_name='test-channel')

        # #######################################
        # tests for osx-64 subdir
        # #######################################
        assert isfile(join(base_location, 'osx-64', 'index.html'))
        assert isfile(join(base_location, 'osx-64', 'repodata.json.bz2'))

        with open(join(base_location, 'osx-64', 'repodata.json')) as fh:
            actual_repodata_json = json.loads(fh.read())
        expected_repodata_json = {
            "info": {
                'subdir': 'osx-64',
            },
            "packages": {
                "conda-index-pkg-a-1.0-py27h5e241af_0.tar.bz2": {
                    "build": "py27h5e241af_0",
                    "build_number": 0,
                    "depends": [
                        "python >=2.7,<2.8.0a0"
                    ],
                    "license": "BSD",
                    "md5": "37861df8111170f5eed4bff27868df59",
                    "name": "conda-index-pkg-a",
                    "sha256": "459f3e9b2178fa33bdc4e6267326405329d1c1ab982273d9a1c0a5084a1ddc30",
                    "size": 8733,
                    "subdir": "osx-64",
                    "timestamp": 1508520039632,
                    "version": "1.0",
                },
            },
            "removed": [],
            "repodata_version": 1,
        }
        assert actual_repodata_json == expected_repodata_json

        # #######################################
        # tests for full channel
        # #######################################

        with open(join(base_location, 'channeldata.json')) as fh:
            actual_channeldata_json = json.loads(fh.read())
        expected_channeldata_json = {
            "channeldata_version": 1,
            "packages": {
                "conda-index-pkg-a": {
                    "description": "Description field for conda-index-pkg-a. Actually, this is just the python description. "
                                   "Python is a widely used high-level, general-purpose, interpreted, dynamic "
                                   "programming language. Its design philosophy emphasizes code "
                                   "readability, and its syntax allows programmers to express concepts in "
                                   "fewer lines of code than would be possible in languages such as C++ or "
                                   "Java. The language provides constructs intended to enable clear programs "
                                   "on both a small and large scale.",
                    "dev_url": "https://github.com/kalefranz/conda-test-packages/blob/master/conda-index-pkg-a/meta.yaml",
                    "doc_source_url": "https://github.com/kalefranz/conda-test-packages/blob/master/conda-index-pkg-a/README.md",
                    "doc_url": "https://github.com/kalefranz/conda-test-packages/blob/master/conda-index-pkg-a",
                    "home": "https://anaconda.org/conda-test/conda-index-pkg-a",
                    "license": "BSD",
                    "reference_package": "osx-64/conda-index-pkg-a-1.0-py27h5e241af_0.tar.bz2",
                    "source_git_rev": "master",
                    "source_git_url": "https://github.com/kalefranz/conda-test-packages.git",
                    "subdirs": [
                        "osx-64",
                    ],
                    "summary": "Summary field for conda-index-pkg-a",
                    "version": "1.0",
                    "activate.d": False,
                    "deactivate.d": False,
                    "post_link": True,
                    "pre_link": False,
                    "pre_unlink": False,
                    "binary_prefix": False,
                    "text_prefix": True,
                    "run_exports": {},
                }
            },
            "subdirs": [
                "noarch",
                "osx-64"
            ]
        }
        assert actual_channeldata_json == expected_channeldata_json


def test_index_noarch_osx64_1():
    with tempdir() as base_location:
        test_package_path = join(base_location, 'osx-64', 'conda-index-pkg-a-1.0-py27h5e241af_0.tar.bz2')
        test_package_url = 'https://conda.anaconda.org/conda-test/osx-64/conda-index-pkg-a-1.0-py27h5e241af_0.tar.bz2'
        download(test_package_url, test_package_path)

        test_package_path = join(base_location, 'noarch', 'conda-index-pkg-a-1.0-pyhed9eced_1.tar.bz2')
        test_package_url = 'https://conda.anaconda.org/conda-test/noarch/conda-index-pkg-a-1.0-pyhed9eced_1.tar.bz2'
        download(test_package_url, test_package_path)

        update_index(base_location, channel_name='test-channel')

        # #######################################
        # tests for osx-64 subdir
        # #######################################
        assert isfile(join(base_location, 'osx-64', 'index.html'))
        assert isfile(join(base_location, 'osx-64', 'repodata.json'))  # repodata is tested in test_index_on_single_subdir_1
        assert isfile(join(base_location, 'osx-64', 'repodata.json.bz2'))

        # #######################################
        # tests for noarch subdir
        # #######################################
        assert isfile(join(base_location, 'osx-64', 'index.html'))
        assert isfile(join(base_location, 'osx-64', 'repodata.json.bz2'))

        with open(join(base_location, 'noarch', 'repodata.json')) as fh:
            actual_repodata_json = json.loads(fh.read())
        expected_repodata_json = {
            "info": {
                'subdir': 'noarch',
            },
            "packages": {
                "conda-index-pkg-a-1.0-pyhed9eced_1.tar.bz2": {
                    "build": "pyhed9eced_1",
                    "build_number": 1,
                    "depends": [
                        "python"
                    ],
                    "license": "BSD",
                    "md5": "56b5f6b7fb5583bccfc4489e7c657484",
                    "name": "conda-index-pkg-a",
                    "noarch": "python",
                    "sha256": "7430743bffd4ac63aa063ae8518e668eac269c783374b589d8078bee5ed4cbc6",
                    "size": 7882,
                    "subdir": "noarch",
                    "timestamp": 1508520204768,
                    "version": "1.0",
                },
            },
            "removed": [],
            "repodata_version": 1,
        }
        assert actual_repodata_json == expected_repodata_json

        # #######################################
        # tests for full channel
        # #######################################

        with open(join(base_location, 'channeldata.json')) as fh:
            actual_channeldata_json = json.loads(fh.read())
        expected_channeldata_json = {
            "channeldata_version": 1,
            "packages": {
                "conda-index-pkg-a": {
                    "description": "Description field for conda-index-pkg-a. Actually, this is just the python description. "
                                   "Python is a widely used high-level, general-purpose, interpreted, dynamic "
                                   "programming language. Its design philosophy emphasizes code "
                                   "readability, and its syntax allows programmers to express concepts in "
                                   "fewer lines of code than would be possible in languages such as C++ or "
                                   "Java. The language provides constructs intended to enable clear programs "
                                   "on both a small and large scale.",
                    "dev_url": "https://github.com/kalefranz/conda-test-packages/blob/master/conda-index-pkg-a/meta.yaml",
                    "doc_source_url": "https://github.com/kalefranz/conda-test-packages/blob/master/conda-index-pkg-a/README.md",
                    "doc_url": "https://github.com/kalefranz/conda-test-packages/blob/master/conda-index-pkg-a",
                    "home": "https://anaconda.org/conda-test/conda-index-pkg-a",
                    "license": "BSD",
                    "reference_package": "noarch/conda-index-pkg-a-1.0-pyhed9eced_1.tar.bz2",
                    "source_git_rev": "master",
                    "source_git_url": "https://github.com/kalefranz/conda-test-packages.git",
                    "subdirs": [
                        "noarch",
                        "osx-64",
                    ],
                    "summary": "Summary field for conda-index-pkg-a. This is the python noarch version.",  # <- tests that the higher noarch build number is the data collected
                    "version": "1.0",
                    "activate.d": False,
                    "deactivate.d": False,
                    "post_link": True,
                    "pre_link": False,
                    "pre_unlink": False,
                    "binary_prefix": False,
                    "text_prefix": False,
                    "run_exports": {},
                }
            },
            "subdirs": [
                "noarch",
                "osx-64",
            ]
        }
        assert actual_channeldata_json == expected_channeldata_json

