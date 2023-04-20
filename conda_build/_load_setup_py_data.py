# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import logging
import os
import sys


def load_setup_py_data(
    setup_file,
    from_recipe_dir=False,
    recipe_dir=None,
    work_dir=None,
    permit_undefined_jinja=True,
):
    _setuptools_data = {}
    log = logging.getLogger(__name__)

    import distutils.core

    import setuptools

    cd_to_work = False
    path_backup = sys.path

    def _change_cwd(target_dir):
        cd_to_work = True
        try:
            cwd = os.getcwd()
        except OSError:
            cwd = recipe_dir or work_dir
        os.chdir(target_dir)
        # this is very important - or else if versioneer or otherwise is in the start folder,
        # things will pick up the wrong versioneer/whatever!
        sys.path.insert(0, target_dir)
        return cd_to_work, cwd

    if from_recipe_dir and recipe_dir:
        setup_file = os.path.abspath(os.path.join(recipe_dir, setup_file))
        # if the setup_file is not in the recipe dir itself, but is say specified as '../setup.py'
        setup_root, _ = os.path.split(setup_file)
        if os.path.abspath(setup_root) != os.path.abspath(recipe_dir):
            cd_to_work, cwd = _change_cwd(setup_root)
    elif os.path.exists(work_dir):
        cd_to_work, cwd = _change_cwd(work_dir)
        if not os.path.isabs(setup_file):
            setup_file = os.path.join(work_dir, setup_file)
    else:
        message = (
            "Did not find setup.py file in manually specified location, and source "
            "not downloaded yet."
        )
        if permit_undefined_jinja:
            log.debug(message)
            return {}
        else:
            raise RuntimeError(message)

    setup_cfg_data = {}
    try:
        try:
            # Recommended for setuptools 61.0.0+
            # (though may disappear in the future)
            from setuptools.config.setupcfg import read_configuration
        except ImportError:
            from setuptools.config import read_configuration
    except ImportError:
        pass  # setuptools <30.3.0 cannot read metadata / options from 'setup.cfg'
    else:
        setup_cfg = os.path.join(os.path.dirname(setup_file), "setup.cfg")
        if os.path.isfile(setup_cfg):
            # read_configuration returns a dict of dicts. Each dict (keys: 'metadata',
            # 'options'), if present, provides keyword arguments for the setup function.
            for kwargs in read_configuration(setup_cfg).values():
                # explicit arguments to setup.cfg take priority over values in setup.py
                setup_cfg_data.update(kwargs)

    def setup(**kw):
        _setuptools_data.update(kw)
        # values in setup.cfg take priority over explicit arguments to setup.py
        _setuptools_data.update(setup_cfg_data)

    # Patch setuptools, distutils
    setuptools_setup = setuptools.setup
    distutils_setup = distutils.core.setup
    numpy_setup = None

    versioneer = None
    if "versioneer" in sys.modules:
        versioneer = sys.modules["versioneer"]
        del sys.modules["versioneer"]

    try:
        import numpy.distutils.core

        numpy_setup = numpy.distutils.core.setup
        numpy.distutils.core.setup = setup
    except ImportError:
        log.debug("Failed to import numpy for setup patch.  Is numpy installed?")

    setuptools.setup = distutils.core.setup = setup
    ns = {
        "__name__": "__main__",
        "__doc__": None,
        "__file__": setup_file,
    }
    if os.path.isfile(setup_file):
        with open(setup_file) as f:
            code = compile(f.read(), setup_file, "exec", dont_inherit=1)
            exec(code, ns, ns)
    else:
        if not permit_undefined_jinja:
            raise TypeError(f"{setup_file} is not a file that can be read")

    sys.modules["versioneer"] = versioneer

    distutils.core.setup = distutils_setup
    setuptools.setup = setuptools_setup
    if numpy_setup:
        numpy.distutils.core.setup = numpy_setup

    if cd_to_work:
        os.chdir(cwd)
    # remove our workdir from sys.path
    sys.path = path_backup
    return _setuptools_data


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="run setup.py file to obtain metadata")
    parser.add_argument(
        "work_dir",
        help=(
            "path to work dir, where we'll write the output data "
            "json, and potentially also where setup.py should be found"
        ),
    )
    parser.add_argument("setup_file", help="path or filename of setup.py file")
    parser.add_argument(
        "--from-recipe-dir",
        help=("look for setup.py file in recipe " "dir (as opposed to work dir)"),
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "--recipe-dir",
        help=("(optional) path to recipe dir, where " "setup.py should be found"),
    )

    parser.add_argument(
        "--permit-undefined-jinja",
        help=("look for setup.py file in recipe " "dir (as opposed to work dir)"),
        default=False,
        action="store_true",
    )
    args = parser.parse_args()
    # we get back a dict of the setup data
    data = load_setup_py_data(**args.__dict__)
    with open(
        os.path.join(args.work_dir, "conda_build_loaded_setup_py.json"), "w"
    ) as f:
        # this is lossy.  Anything that can't be serialized is either forced to None or
        #     removed completely.
        json.dump(data, f, skipkeys=True, default=lambda x: None)
