# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

import json
from logging import getLogger
import os
from os.path import dirname, isdir, join, isfile
import requests
import shutil
import tarfile

import mock
import conda_package_handling.api

from conda_build import api
import conda_build.index
from conda_build.utils import copy_into, rm_rf
from conda_build.conda_interface import subdir
from conda_build.conda_interface import conda_47
from .utils import metadata_dir, archive_dir

log = getLogger(__name__)

# NOTE: The recipes for test packages used in this module are at https://github.com/kalefranz/conda-test-packages


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


def test_index_on_single_subdir_1(testing_workdir):
    test_package_path = join(testing_workdir, 'osx-64', 'conda-index-pkg-a-1.0-py27h5e241af_0.tar.bz2')
    test_package_url = 'https://conda.anaconda.org/conda-test/osx-64/conda-index-pkg-a-1.0-py27h5e241af_0.tar.bz2'
    download(test_package_url, test_package_path)

    conda_build.index.update_index(testing_workdir, channel_name='test-channel')

    # #######################################
    # tests for osx-64 subdir
    # #######################################
    assert isfile(join(testing_workdir, 'osx-64', 'index.html'))
    assert isfile(join(testing_workdir, 'osx-64', 'repodata.json.bz2'))
    assert isfile(join(testing_workdir, 'osx-64', 'repodata_from_packages.json.bz2'))

    with open(join(testing_workdir, 'osx-64', 'repodata.json')) as fh:
        actual_repodata_json = json.loads(fh.read())
    with open(join(testing_workdir, 'osx-64', 'repodata_from_packages.json')) as fh:
        actual_pkg_repodata_json = json.loads(fh.read())
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
        "packages.conda": {},
        "removed": [],
        "repodata_version": 1,
    }
    assert actual_repodata_json == expected_repodata_json
    assert actual_pkg_repodata_json == expected_repodata_json

    # #######################################
    # tests for full channel
    # #######################################

    with open(join(testing_workdir, 'channeldata.json')) as fh:
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


def test_index_noarch_osx64_1(testing_workdir):
    test_package_path = join(testing_workdir, 'osx-64', 'conda-index-pkg-a-1.0-py27h5e241af_0.tar.bz2')
    test_package_url = 'https://conda.anaconda.org/conda-test/osx-64/conda-index-pkg-a-1.0-py27h5e241af_0.tar.bz2'
    download(test_package_url, test_package_path)

    test_package_path = join(testing_workdir, 'noarch', 'conda-index-pkg-a-1.0-pyhed9eced_1.tar.bz2')
    test_package_url = 'https://conda.anaconda.org/conda-test/noarch/conda-index-pkg-a-1.0-pyhed9eced_1.tar.bz2'
    download(test_package_url, test_package_path)

    conda_build.index.update_index(testing_workdir, channel_name='test-channel')

    # #######################################
    # tests for osx-64 subdir
    # #######################################
    assert isfile(join(testing_workdir, 'osx-64', 'index.html'))
    assert isfile(join(testing_workdir, 'osx-64', 'repodata.json'))  # repodata is tested in test_index_on_single_subdir_1
    assert isfile(join(testing_workdir, 'osx-64', 'repodata.json.bz2'))
    assert isfile(join(testing_workdir, 'osx-64', 'repodata_from_packages.json'))
    assert isfile(join(testing_workdir, 'osx-64', 'repodata_from_packages.json.bz2'))

    # #######################################
    # tests for noarch subdir
    # #######################################
    assert isfile(join(testing_workdir, 'noarch', 'index.html'))
    assert isfile(join(testing_workdir, 'noarch', 'repodata.json.bz2'))
    assert isfile(join(testing_workdir, 'noarch', 'repodata_from_packages.json.bz2'))

    with open(join(testing_workdir, 'noarch', 'repodata.json')) as fh:
        actual_repodata_json = json.loads(fh.read())
    with open(join(testing_workdir, 'noarch', 'repodata_from_packages.json')) as fh:
        actual_pkg_repodata_json = json.loads(fh.read())
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
        "packages.conda": {},
        "removed": [],
        "repodata_version": 1,
    }
    assert actual_repodata_json == expected_repodata_json
    assert actual_pkg_repodata_json == expected_repodata_json

    # #######################################
    # tests for full channel
    # #######################################

    with open(join(testing_workdir, 'channeldata.json')) as fh:
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
                "text_prefix": True,
                "run_exports": {},
            }
        },
        "subdirs": [
            "noarch",
            "osx-64",
        ]
    }
    assert actual_channeldata_json == expected_channeldata_json


def _build_test_index(workdir):
    pkgs = api.build(os.path.join(metadata_dir, "_index_hotfix_pkgs"), croot=workdir)
    for pkg in pkgs:
        conda_package_handling.api.transmute(pkg, '.conda')
    api.update_index(workdir)

    with open(os.path.join(workdir, subdir, 'repodata.json')) as f:
        original_metadata = json.load(f)

    pkg_list = original_metadata['packages']
    assert "track_features_test-1.0-0.tar.bz2" in pkg_list
    assert pkg_list["track_features_test-1.0-0.tar.bz2"]["track_features"] == "dummy"

    assert "hotfix_depends_test-1.0-dummy_0.tar.bz2" in pkg_list
    assert pkg_list["hotfix_depends_test-1.0-dummy_0.tar.bz2"]["features"] == "dummy"
    assert "zlib" in pkg_list["hotfix_depends_test-1.0-dummy_0.tar.bz2"]["depends"]

    assert "revoke_test-1.0-0.tar.bz2" in pkg_list
    assert "zlib" in pkg_list["revoke_test-1.0-0.tar.bz2"]["depends"]
    assert "package_has_been_revoked" not in pkg_list["revoke_test-1.0-0.tar.bz2"]["depends"]

    assert "remove_test-1.0-0.tar.bz2" in pkg_list


def test_gen_patch_py(testing_workdir):
    """
    This is a channel-wide file that applies to many subdirs.  It must have a function with this signature:

    def _patch_repodata(repodata, subdir):

    That function must return a dictionary of patch instructions, of the form:

    {
        "patch_instructions_version": 1,
        "packages": defaultdict(dict),
        "revoke": [],
        "remove": [],
    }

    revoke and remove are lists of filenames. remove makes the file not show up
    in the index (it may still be downloadable with a direct URL to the file).
    revoke makes packages uninstallable by adding an unsatisfiable dependency.
    This can be made installable by including a channel that has that package
    (to be created by @jjhelmus).

    packages is a dictionary, where keys are package filenames. Values are
    dictionaries similar to the contents of each package in repodata.json. Any
    values in provided in packages here overwrite the values in repodata.json.
    Any value set to None is removed.
    """
    _build_test_index(testing_workdir)

    func = """
def _patch_repodata(repodata, subdir):
    pkgs = repodata["packages"]
    import fnmatch
    replacement_dict = {}
    if "track_features_test-1.0-0.tar.bz2" in pkgs:
        replacement_dict["track_features_test-1.0-0.tar.bz2"] = {"track_features": None}
    if "hotfix_depends_test-1.0-dummy_0.tar.bz2" in pkgs:
        replacement_dict["hotfix_depends_test-1.0-dummy_0.tar.bz2"] = {
                             "depends": pkgs["hotfix_depends_test-1.0-dummy_0.tar.bz2"]["depends"] + ["dummy"],
                             "features": None}
    revoke_list = [pkg for pkg in pkgs if fnmatch.fnmatch(pkg, "revoke_test*")]
    remove_list = [pkg for pkg in pkgs if fnmatch.fnmatch(pkg, "remove_test*")]
    return {
        "patch_instructions_version": 1,
        "packages": replacement_dict,
        "revoke": revoke_list,
        "remove": remove_list,
    }
"""
    patch_file = os.path.join(testing_workdir, 'repodata_patch.py')
    with open(patch_file, 'w') as f:
        f.write(func)

    # indexing a second time with the same patchset should keep the removals
    for i in (1, 2):
        conda_build.index.update_index(testing_workdir, patch_generator=patch_file, verbose=True)
        with open(os.path.join(testing_workdir, subdir, 'repodata.json')) as f:
            patched_metadata = json.load(f)

        pkg_list = patched_metadata['packages']
        assert "track_features_test-1.0-0.tar.bz2" in pkg_list
        assert "track_features" not in pkg_list["track_features_test-1.0-0.tar.bz2"]
        print("pass %s track features ok" % i)

        assert "hotfix_depends_test-1.0-dummy_0.tar.bz2" in pkg_list
        assert "features" not in pkg_list["hotfix_depends_test-1.0-dummy_0.tar.bz2"]
        assert "zlib" in pkg_list["hotfix_depends_test-1.0-dummy_0.tar.bz2"]["depends"]
        assert "dummy" in pkg_list["hotfix_depends_test-1.0-dummy_0.tar.bz2"]["depends"]
        print("pass %s hotfix ok" % i)

        assert "revoke_test-1.0-0.tar.bz2" in pkg_list
        assert "zlib" in pkg_list["revoke_test-1.0-0.tar.bz2"]["depends"]
        assert "package_has_been_revoked" in pkg_list["revoke_test-1.0-0.tar.bz2"]["depends"]
        print("pass %s revoke ok" % i)

        assert "remove_test-1.0-0.tar.bz2" not in pkg_list
        assert "remove_test-1.0-0.tar.bz2" in patched_metadata['removed'], "removed list not populated in run %d" % i
        print("pass %s remove ok" % i)

        with open(os.path.join(testing_workdir, subdir, 'repodata_from_packages.json')) as f:
            pkg_metadata = json.load(f)

        pkg_list = pkg_metadata['packages']
        assert "track_features_test-1.0-0.tar.bz2" in pkg_list
        assert pkg_list["track_features_test-1.0-0.tar.bz2"]["track_features"] == "dummy"

        assert "hotfix_depends_test-1.0-dummy_0.tar.bz2" in pkg_list
        assert pkg_list["hotfix_depends_test-1.0-dummy_0.tar.bz2"]["features"] == "dummy"
        assert "zlib" in pkg_list["hotfix_depends_test-1.0-dummy_0.tar.bz2"]["depends"]

        assert "revoke_test-1.0-0.tar.bz2" in pkg_list
        assert "zlib" in pkg_list["revoke_test-1.0-0.tar.bz2"]["depends"]
        assert "package_has_been_revoked" not in pkg_list["revoke_test-1.0-0.tar.bz2"]["depends"]


def test_channel_patch_instructions_json(testing_workdir):
    _build_test_index(testing_workdir)

    replacement_dict = {}
    replacement_dict["track_features_test-1.0-0.tar.bz2"] = {"track_features": None}
    replacement_dict["hotfix_depends_test-1.0-dummy_0.tar.bz2"] = {
                             "depends": ["zlib", "dummy"],
                             "features": None}

    patch = {
        "patch_instructions_version": 1,
        "packages": replacement_dict,
        "revoke": ["revoke_test-1.0-0.tar.bz2"],
        "remove": ["remove_test-1.0-0.tar.bz2"],
    }

    with open(os.path.join(testing_workdir, subdir, 'patch_instructions.json'), 'w') as f:
        json.dump(patch, f)

    conda_build.index.update_index(testing_workdir)

    with open(os.path.join(testing_workdir, subdir, 'repodata.json')) as f:
        patched_metadata = json.load(f)

    formats = (('packages', '.tar.bz2'), ('packages.conda', '.conda'))

    for key, ext in formats:
        pkg_list = patched_metadata[key]
        assert "track_features_test-1.0-0" + ext in pkg_list
        assert "track_features" not in pkg_list["track_features_test-1.0-0" + ext]

        assert "hotfix_depends_test-1.0-dummy_0" + ext in pkg_list
        assert "features" not in pkg_list["hotfix_depends_test-1.0-dummy_0" + ext]
        assert "zlib" in pkg_list["hotfix_depends_test-1.0-dummy_0" + ext]["depends"]
        assert "dummy" in pkg_list["hotfix_depends_test-1.0-dummy_0" + ext]["depends"]

        assert "revoke_test-1.0-0" + ext in pkg_list
        assert "zlib" in pkg_list["revoke_test-1.0-0" + ext]["depends"]
        assert "package_has_been_revoked" in pkg_list["revoke_test-1.0-0" + ext]["depends"]

        assert "remove_test-1.0-0" + ext not in pkg_list

        with open(os.path.join(testing_workdir, subdir, 'repodata_from_packages.json')) as f:
            pkg_repodata = json.load(f)

        pkg_list = pkg_repodata[key]
        assert "track_features_test-1.0-0" + ext in pkg_list
        assert pkg_list["track_features_test-1.0-0" + ext]["track_features"] == "dummy"

        assert "hotfix_depends_test-1.0-dummy_0" + ext in pkg_list
        assert pkg_list["hotfix_depends_test-1.0-dummy_0" + ext]["features"] == "dummy"
        assert "zlib" in pkg_list["hotfix_depends_test-1.0-dummy_0" + ext]["depends"]

        assert "revoke_test-1.0-0" + ext in pkg_list
        assert "zlib" in pkg_list["revoke_test-1.0-0" + ext]["depends"]
        assert "package_has_been_revoked" not in pkg_list["revoke_test-1.0-0" + ext]["depends"]

        assert "remove_test-1.0-0" + ext in pkg_list


def test_patch_from_tarball(testing_workdir):
    """This is how we expect external communities to provide patches to us.
    We can't let them just give us Python files for us to run, because of the
    security risk of arbitrary code execution."""
    _build_test_index(testing_workdir)

    # our hotfix metadata can be generated any way you want.  Hard-code this here, but in general,
    #    people will use some python file to generate this.

    replacement_dict = {}
    replacement_dict["track_features_test-1.0-0.tar.bz2"] = {"track_features": None}
    replacement_dict["hotfix_depends_test-1.0-dummy_0.tar.bz2"] = {
                             "depends": ["zlib", "dummy"],
                             "features": None}

    patch = {
        "patch_instructions_version": 1,
        "packages": replacement_dict,
        "revoke": ["revoke_test-1.0-0.tar.bz2"],
        "remove": ["remove_test-1.0-0.tar.bz2"],
    }
    with open("patch_instructions.json", "w") as f:
        json.dump(patch, f)

    with tarfile.open("patch_archive.tar.bz2", "w:bz2") as archive:
        archive.add("patch_instructions.json", "%s/patch_instructions.json" % subdir)

    conda_build.index.update_index(testing_workdir, patch_generator="patch_archive.tar.bz2")

    with open(os.path.join(testing_workdir, subdir, 'repodata.json')) as f:
        patched_metadata = json.load(f)

    pkg_list = patched_metadata['packages']
    assert "track_features_test-1.0-0.tar.bz2" in pkg_list
    assert "track_features" not in pkg_list["track_features_test-1.0-0.tar.bz2"]

    assert "hotfix_depends_test-1.0-dummy_0.tar.bz2" in pkg_list
    assert "features" not in pkg_list["hotfix_depends_test-1.0-dummy_0.tar.bz2"]
    assert "zlib" in pkg_list["hotfix_depends_test-1.0-dummy_0.tar.bz2"]["depends"]
    assert "dummy" in pkg_list["hotfix_depends_test-1.0-dummy_0.tar.bz2"]["depends"]

    assert "revoke_test-1.0-0.tar.bz2" in pkg_list
    assert "zlib" in pkg_list["revoke_test-1.0-0.tar.bz2"]["depends"]
    assert "package_has_been_revoked" in pkg_list["revoke_test-1.0-0.tar.bz2"]["depends"]

    assert "remove_test-1.0-0.tar.bz2" not in pkg_list

    with open(os.path.join(testing_workdir, subdir, 'repodata_from_packages.json')) as f:
        pkg_repodata = json.load(f)

    pkg_list = pkg_repodata['packages']
    assert "track_features_test-1.0-0.tar.bz2" in pkg_list
    assert pkg_list["track_features_test-1.0-0.tar.bz2"]["track_features"] == "dummy"

    assert "hotfix_depends_test-1.0-dummy_0.tar.bz2" in pkg_list
    assert pkg_list["hotfix_depends_test-1.0-dummy_0.tar.bz2"]["features"] == "dummy"
    assert "zlib" in pkg_list["hotfix_depends_test-1.0-dummy_0.tar.bz2"]["depends"]

    assert "revoke_test-1.0-0.tar.bz2" in pkg_list
    assert "zlib" in pkg_list["revoke_test-1.0-0.tar.bz2"]["depends"]
    assert "package_has_been_revoked" not in pkg_list["revoke_test-1.0-0.tar.bz2"]["depends"]

    assert "remove_test-1.0-0.tar.bz2" in pkg_list


def test_index_of_removed_pkg(testing_metadata):
    out_files = api.build(testing_metadata)
    for f in out_files:
        os.remove(f)
    api.update_index(testing_metadata.config.croot)
    with open(os.path.join(testing_metadata.config.croot, subdir, 'repodata.json')) as f:
        repodata = json.load(f)
    assert not repodata['packages']
    with open(os.path.join(testing_metadata.config.croot, subdir, 'repodata_from_packages.json')) as f:
        repodata = json.load(f)
    assert not repodata['packages']


def test_patch_instructions_with_missing_subdir(testing_workdir):
    os.makedirs('linux-64')
    os.makedirs('zos-z')
    api.update_index('.')
    # we use conda-forge's patch instructions because they don't have zos-z data, and that triggers an error
    pkg = "conda-forge-repodata-patches"
    url = "https://anaconda.org/conda-forge/{0}/20180828/download/noarch/{0}-20180828-0.tar.bz2".format(pkg)
    patch_instructions = download(url, os.path.join(os.getcwd(), "patches.tar.bz2"))
    api.update_index('.', patch_generator=patch_instructions)


def test_stat_cache_used(testing_workdir, mocker):
    test_package_path = join(testing_workdir, 'osx-64', 'conda-index-pkg-a-1.0-py27h5e241af_0.tar.bz2')
    test_package_url = 'https://conda.anaconda.org/conda-test/osx-64/conda-index-pkg-a-1.0-py27h5e241af_0.tar.bz2'
    download(test_package_url, test_package_path)
    conda_build.index.update_index(testing_workdir, channel_name='test-channel')

    cph_extract = mocker.spy(conda_package_handling.api, 'extract')
    conda_build.index.update_index(testing_workdir, channel_name='test-channel')
    cph_extract.assert_not_called()


def test_new_pkg_format_preferred(testing_workdir, mocker):
    """Test that in one pass, the .conda file is extracted before the .tar.bz2, and the .tar.bz2 uses the cache"""
    test_package_path = join(testing_workdir, 'osx-64', 'conda-index-pkg-a-1.0-py27h5e241af_0')
    exts = ('.tar.bz2', '.conda')
    for ext in exts:
        copy_into(os.path.join(archive_dir, 'conda-index-pkg-a-1.0-py27h5e241af_0' + ext), test_package_path + ext)
    # mock the extract function, so that we can assert that it is not called
    #     with the .tar.bz2, because the .conda should be preferred
    cph_extract = mocker.spy(conda_package_handling.api, 'extract')
    conda_build.index.update_index(testing_workdir, channel_name='test-channel', debug=True)
    # extract should get called once by default.  Within a channel, we assume that a .tar.bz2 and .conda have the same contents.
    cph_extract.assert_called_once_with(test_package_path + '.conda', mock.ANY, 'info')

    with open(join(testing_workdir, 'osx-64', 'repodata.json')) as fh:
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
        "packages.conda": {
            "conda-index-pkg-a-1.0-py27h5e241af_0.conda": {
                "build": "py27h5e241af_0",
                "build_number": 0,
                "depends": [
                    "python >=2.7,<2.8.0a0"
                ],
                "license": "BSD",
                "md5": "4ed4b435f400dac1aabdc1fff06f78ff",
                "name": "conda-index-pkg-a",
                "sha256": "67b07b644105439515cc5c8c22c86939514cacf30c8c574cd70f5f1267a40f19",
                "size": 9296,
                "subdir": "osx-64",
                "timestamp": 1508520039632,
                "version": "1.0",
            },
        },
        "removed": [],
        "repodata_version": 1,
    }
    assert actual_repodata_json == expected_repodata_json

    # if we clear the stat cache, we force a re-examination.  This re-examination will load files
    #     from the cache.  This has been a source of bugs in the past, where the wrong cached file
    #     being loaded resulted in incorrect hashes/sizes for either the .tar.bz2 or .conda, depending
    #     on which of those 2 existed in the cache.
    rm_rf(os.path.join(testing_workdir, 'osx-64', 'stat.json'))
    conda_build.index.update_index(testing_workdir, channel_name='test-channel', debug=True)

    with open(join(testing_workdir, 'osx-64', 'repodata.json')) as fh:
        actual_repodata_json = json.loads(fh.read())

    assert actual_repodata_json == expected_repodata_json


def test_new_pkg_format_stat_cache_used(testing_workdir, mocker):
    # if we have old .tar.bz2 index cache stuff, assert that we pick up correct md5, sha26 and size for .conda
    test_package_path = join(testing_workdir, 'osx-64', 'conda-index-pkg-a-1.0-py27h5e241af_0')
    copy_into(os.path.join(archive_dir, 'conda-index-pkg-a-1.0-py27h5e241af_0' + '.tar.bz2'), test_package_path + '.tar.bz2')
    conda_build.index.update_index(testing_workdir, channel_name='test-channel')

    # mock the extract function, so that we can assert that it is not called, because the stat cache should exist
    #    if this doesn't work, something about the stat cache is confused.  It's a little convoluted, because
    #    the index has keys for .tar.bz2's, but the stat cache comes from .conda files when they are available
    #    because extracting them is much, much faster.
    copy_into(os.path.join(archive_dir, 'conda-index-pkg-a-1.0-py27h5e241af_0' + '.conda'), test_package_path + '.conda')
    cph_extract = mocker.spy(conda_package_handling.api, 'extract')
    conda_build.index.update_index(testing_workdir, channel_name='test-channel', debug=True)
    cph_extract.assert_not_called()

    with open(join(testing_workdir, 'osx-64', 'repodata.json')) as fh:
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
        "packages.conda": {
            "conda-index-pkg-a-1.0-py27h5e241af_0.conda": {
                "build": "py27h5e241af_0",
                "build_number": 0,
                "depends": [
                    "python >=2.7,<2.8.0a0"
                ],
                "license": "BSD",
                "md5": "4ed4b435f400dac1aabdc1fff06f78ff",
                "name": "conda-index-pkg-a",
                "sha256": "67b07b644105439515cc5c8c22c86939514cacf30c8c574cd70f5f1267a40f19",
                "size": 9296,
                "subdir": "osx-64",
                "timestamp": 1508520039632,
                "version": "1.0",
            },
        },
        "removed": [],
        "repodata_version": 1,
    }
    assert actual_repodata_json == expected_repodata_json


def test_current_index_reduces_space():
    repodata = os.path.join(os.path.dirname(__file__), 'index_data', 'time_cut', 'repodata.json')
    with open(repodata) as f:
        repodata = json.load(f)
    assert len(repodata['packages']) == 7
    assert len(repodata['packages.conda']) == 3
    trimmed_repodata = conda_build.index._build_current_repodata("linux-64", repodata, None)

    tar_bz2_keys = {"two-because-satisfiability-1.2.11-h7b6447c_3.tar.bz2",
                    "two-because-satisfiability-1.2.10-h7b6447c_3.tar.bz2",
                    "depends-on-older-1.2.10-h7b6447c_3.tar.bz2",
                    "ancient-package-1.2.10-h7b6447c_3.tar.bz2",
                    "one-gets-filtered-1.3.10-h7b6447c_3.tar.bz2"
    }
    # conda 4.7 removes .tar.bz2 files in favor of .conda files
    if conda_47:
        tar_bz2_keys.remove("one-gets-filtered-1.3.10-h7b6447c_3.tar.bz2")

    # .conda files will replace .tar.bz2 files.  Older packages that are necessary for satisfiability will remain
    assert set(trimmed_repodata['packages'].keys()) == tar_bz2_keys
    if conda_47:
        assert set(trimmed_repodata['packages.conda'].keys()) == {"one-gets-filtered-1.3.10-h7b6447c_3.conda"}

    # we can keep more than one version series using a collection of keys
    trimmed_repodata = conda_build.index._build_current_repodata("linux-64", repodata, {'one-gets-filtered': ['1.2', '1.3']})
    if conda_47:
        assert set(trimmed_repodata['packages.conda'].keys()) == {"one-gets-filtered-1.2.11-h7b6447c_3.conda",
                                                                  "one-gets-filtered-1.3.10-h7b6447c_3.conda"}
    else:
        assert set(trimmed_repodata['packages'].keys()) == tar_bz2_keys | {"one-gets-filtered-1.2.11-h7b6447c_3.tar.bz2"}


def test_current_index_version_keys_keep_older_packages(testing_workdir):
    pkg_dir = os.path.join(os.path.dirname(__file__), 'index_data', 'packages')

    # pass no version file
    api.update_index(pkg_dir)
    with open(os.path.join(pkg_dir, 'osx-64', 'current_repodata.json')) as f:
        repodata = json.load(f)
    # only the newest version is kept
    assert len(repodata['packages']) == 1
    assert list(repodata['packages'].values())[0]['version'] == "2.0"

    # pass version file
    api.update_index(pkg_dir, current_index_versions=os.path.join(pkg_dir, 'versions.yml'))
    with open(os.path.join(pkg_dir, 'osx-64', 'current_repodata.json')) as f:
        repodata = json.load(f)
    assert len(repodata['packages']) == 2

    # pass dict that is equivalent to version file
    api.update_index(pkg_dir, current_index_versions={'dummy-package': ["1.0"]})
    with open(os.path.join(pkg_dir, 'osx-64', 'current_repodata.json')) as f:
        repodata = json.load(f)
    assert list(repodata['packages'].values())[0]['version'] == "1.0"
