# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import json
import os
import sys
from glob import glob

from conda_build.cli import main_metapackage
from conda_build.utils import package_has_file


def test_metapackage(testing_config, testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    args = ["metapackage_test", "1.0", "-d", "bzip2", "--no-anaconda-upload"]
    main_metapackage.execute(args)
    test_path = glob(
        os.path.join(
            sys.prefix,
            "conda-bld",
            testing_config.host_subdir,
            "metapackage_test-1.0-0.tar.bz2",
        )
    )[0]
    assert os.path.isfile(test_path)


def test_metapackage_build_number(testing_config, testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    args = [
        "metapackage_test_build_number",
        "1.0",
        "-d",
        "bzip2",
        "--build-number",
        "1",
        "--no-anaconda-upload",
    ]
    main_metapackage.execute(args)
    test_path = glob(
        os.path.join(
            sys.prefix,
            "conda-bld",
            testing_config.host_subdir,
            "metapackage_test_build_number-1.0-1.tar.bz2",
        )
    )[0]
    assert os.path.isfile(test_path)


def test_metapackage_build_string(testing_config, testing_workdir):
    """the metapackage command creates a package with runtime dependencies specified on the CLI"""
    args = [
        "metapackage_test_build_string",
        "1.0",
        "-d",
        "bzip2",
        "--build-string",
        "frank",
        "--no-anaconda-upload",
    ]
    main_metapackage.execute(args)
    test_path = glob(
        os.path.join(
            sys.prefix,
            "conda-bld",
            testing_config.host_subdir,
            "metapackage_test_build_string-1.0-frank*.tar.bz2",
        )
    )[0]
    assert os.path.isfile(test_path)


def test_metapackage_metadata(testing_config, testing_workdir):
    args = [
        "metapackage_testing_metadata",
        "1.0",
        "-d",
        "bzip2",
        "--home",
        "http://abc.com",
        "--summary",
        "wee",
        "--license",
        "BSD",
        "--no-anaconda-upload",
    ]
    main_metapackage.execute(args)

    test_path = glob(
        os.path.join(
            sys.prefix,
            "conda-bld",
            testing_config.host_subdir,
            "metapackage_testing_metadata-1.0-0.tar.bz2",
        )
    )[0]
    assert os.path.isfile(test_path)
    info = json.loads(package_has_file(test_path, "info/index.json"))
    assert info["license"] == "BSD"
    info = json.loads(package_has_file(test_path, "info/about.json"))
    assert info["home"] == "http://abc.com"
    assert info["summary"] == "wee"
