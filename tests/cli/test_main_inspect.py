# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import re
import sys

import pytest
import yaml

from conda_build import api
from conda_build.cli import main_inspect
from conda_build.utils import on_win

from ..utils import metadata_dir


def test_inspect_installable(testing_workdir):
    args = ["channels", "--test-installable", "conda-team"]
    main_inspect.execute(args)


def test_inspect_linkages(testing_workdir, capfd):
    # get a package that has known object output
    args = ["linkages", "python"]
    if sys.platform == "win32":
        with pytest.raises(SystemExit) as exc:
            main_inspect.execute(args)
            assert "conda inspect linkages is only implemented in Linux and OS X" in exc
    else:
        main_inspect.execute(args)
        output, error = capfd.readouterr()
        assert "libncursesw" in output


def test_inspect_objects(testing_workdir, capfd):
    # get a package that has known object output
    args = ["objects", "python"]
    if sys.platform != "darwin":
        with pytest.raises(SystemExit) as exc:
            main_inspect.execute(args)
            assert "conda inspect objects is only implemented in OS X" in exc
    else:
        main_inspect.execute(args)
        output, error = capfd.readouterr()
        assert re.search("rpath:.*@loader_path", output)


@pytest.mark.skipif(on_win, reason="Windows prefix length doesn't matter (yet?)")
def test_inspect_prefix_length(testing_workdir, capfd):
    from conda_build import api

    # build our own known-length package here
    test_base = os.path.expanduser("~/cbtmp")
    config = api.Config(croot=test_base, anaconda_upload=False, verbose=True)
    recipe_path = os.path.join(metadata_dir, "has_prefix_files")
    config.prefix_length = 80
    outputs = api.build(recipe_path, config=config, notest=True)

    args = ["prefix-lengths"] + outputs
    with pytest.raises(SystemExit):
        main_inspect.execute(args)
        output, error = capfd.readouterr()
        assert "Packages with binary prefixes shorter than" in output
        assert all(fn in output for fn in outputs)

    config.prefix_length = 255
    # reset the build id so that a new one is computed
    config._build_id = ""
    api.build(recipe_path, config=config, notest=True)
    main_inspect.execute(args)
    output, error = capfd.readouterr()
    assert "No packages found with binary prefixes shorter" in output


def test_inspect_hash_input(testing_metadata, testing_workdir, capfd):
    testing_metadata.meta["requirements"]["build"] = ["zlib"]
    api.output_yaml(testing_metadata, "meta.yaml")
    output = api.build(testing_workdir, notest=True)[0]
    with open(os.path.join(testing_workdir, "conda_build_config.yaml"), "w") as f:
        yaml.dump({"zlib": ["1.2.11"]}, f)
    args = ["hash-inputs", output]
    main_inspect.execute(args)
    output, error = capfd.readouterr()
    assert "zlib" in output
