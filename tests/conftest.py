# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterator

import pytest
from conda.common.compat import on_mac, on_win
from pytest import MonkeyPatch

import conda_build
import conda_build.config
from conda_build.config import (
    Config,
    _get_or_merge_config,
    _src_cache_root_default,
    conda_pkg_format_default,
    enable_static_default,
    error_overdepending_default,
    error_overlinking_default,
    exit_on_verify_error_default,
    filename_hashing_default,
    ignore_verify_codes_default,
    no_rewrite_stdout_env_default,
    noarch_python_build_age_default,
)
from conda_build.metadata import MetaData
from conda_build.utils import check_call_env, copy_into, prepend_bin_path
from conda_build.variants import get_default_variant


@pytest.hookimpl
def pytest_report_header(config: pytest.Config):
    # ensuring the expected development conda is being run
    expected = Path(__file__).parent.parent / "conda_build" / "__init__.py"
    assert expected.samefile(conda_build.__file__)
    return f"conda_build.__file__: {conda_build.__file__}"


@pytest.fixture(scope="function")
def testing_workdir(monkeypatch: MonkeyPatch, tmp_path: Path) -> Iterator[str]:
    """Create a workdir in a safe temporary folder; cd into dir above before test, cd out after

    :param tmpdir: py.test fixture, will be injected
    :param request: py.test fixture-related, will be injected (see pytest docs)
    """
    saved_path = Path.cwd()
    monkeypatch.chdir(tmp_path)

    # temporary folder for profiling output, if any
    prof = tmp_path / "prof"
    prof.mkdir(parents=True)

    yield str(tmp_path)

    # if the original CWD has a prof folder, copy any new prof files into it
    if (saved_path / "prof").is_dir() and prof.is_dir():
        for file in prof.glob("*.prof"):
            copy_into(str(file), str(saved_path / "prof" / file.name))


@pytest.fixture(scope="function")
def testing_homedir() -> Iterator[Path]:
    """Create a temporary testing directory in the users home directory; cd into dir before test, cd out after."""
    saved = Path.cwd()
    try:
        with tempfile.TemporaryDirectory(dir=Path.home(), prefix=".pytest_") as home:
            os.chdir(home)

            yield home

            os.chdir(saved)
    except OSError:
        pytest.xfail(
            f"failed to create temporary directory () in {'%HOME%' if on_win else '${HOME}'} "
            "(tmpfs inappropriate for xattrs)"
        )


@pytest.fixture(scope="function")
def testing_config(testing_workdir):
    def boolify(v):
        return v == "true"

    testing_config_kwargs = dict(
        croot=testing_workdir,
        anaconda_upload=False,
        verbose=True,
        activate=False,
        debug=False,
        test_run_post=False,
        # These bits ensure that default values are used instead of any
        # present in ~/.condarc
        filename_hashing=filename_hashing_default,
        _src_cache_root=_src_cache_root_default,
        error_overlinking=boolify(error_overlinking_default),
        error_overdepending=boolify(error_overdepending_default),
        noarch_python_build_age=noarch_python_build_age_default,
        enable_static=boolify(enable_static_default),
        no_rewrite_stdout_env=boolify(no_rewrite_stdout_env_default),
        ignore_verify_codes=ignore_verify_codes_default,
        exit_on_verify_error=exit_on_verify_error_default,
        conda_pkg_format=conda_pkg_format_default,
    )
    result = Config(variant=None, **testing_config_kwargs)
    result._testing_config_kwargs = testing_config_kwargs
    assert result.no_rewrite_stdout_env is False
    assert result._src_cache_root is None
    assert result.src_cache_root == testing_workdir
    assert result.noarch_python_build_age == 0
    return result


@pytest.fixture(scope="function", autouse=True)
def default_testing_config(testing_config, monkeypatch, request):
    """Monkeypatch get_or_merge_config to use testing_config by default

    This requests fixture testing_config, thus implicitly testing_workdir, too.
    """

    # Allow single tests to disable this fixture even if outer scope adds it.
    if "no_default_testing_config" in request.keywords:
        return

    def get_or_merge_testing_config(config, variant=None, **kwargs):
        if not config:
            # If no existing config, override kwargs that are None with testing config defaults.
            # (E.g., "croot" is None if called via "(..., *args.__dict__)" in cli.main_build.)
            kwargs.update(
                {
                    key: value
                    for key, value in testing_config._testing_config_kwargs.items()
                    if kwargs.get(key) is None
                }
            )
        return _get_or_merge_config(config, variant, **kwargs)

    monkeypatch.setattr(
        conda_build.config,
        "_get_or_merge_config",
        get_or_merge_testing_config,
    )


@pytest.fixture(scope="function")
def testing_metadata(request, testing_config):
    d = defaultdict(dict)
    d["package"]["name"] = request.function.__name__
    d["package"]["version"] = "1.0"
    d["build"]["number"] = "1"
    d["build"]["entry_points"] = []
    d["requirements"]["build"] = []
    d["requirements"]["run"] = []
    d["test"]["commands"] = ['echo "A-OK"', "exit 0"]
    d["about"]["home"] = "sweet home"
    d["about"]["license"] = "contract in blood"
    d["about"]["summary"] = "a test package"
    d["about"]["tags"] = ["a", "b"]
    d["about"]["identifiers"] = "a"
    testing_config.variant = get_default_variant(testing_config)
    testing_config.variants = [testing_config.variant]
    return MetaData.fromdict(d, config=testing_config)


@pytest.fixture(scope="function")
def testing_env(testing_workdir, request, monkeypatch):
    env_path = os.path.join(testing_workdir, "env")

    check_call_env(
        [
            "conda",
            "create",
            "-yq",
            "-p",
            env_path,
            "python={}".format(".".join(sys.version.split(".")[:2])),
        ]
    )
    monkeypatch.setenv(
        "PATH",
        prepend_bin_path(os.environ.copy(), env_path, prepend_prefix=True)["PATH"],
    )
    # cleanup is done by just cleaning up the testing_workdir
    return env_path


@pytest.fixture(
    scope="function",
    params=[
        pytest.param({}, id="default MACOSX_DEPLOYMENT_TARGET"),
        pytest.param(
            {"MACOSX_DEPLOYMENT_TARGET": ["10.9"]},
            id="override MACOSX_DEPLOYMENT_TARGET",
        ),
    ]
    if on_mac
    else [
        pytest.param({}, id="no MACOSX_DEPLOYMENT_TARGET"),
    ],
)
def variants_conda_build_sysroot(monkeypatch, request):
    if not on_mac:
        return {}

    monkeypatch.setenv(
        "CONDA_BUILD_SYSROOT",
        subprocess.run(
            ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
    )
    monkeypatch.setenv(
        "MACOSX_DEPLOYMENT_TARGET",
        subprocess.run(
            ["xcrun", "--sdk", "macosx", "--show-sdk-version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
    )
    return request.param


@pytest.fixture(scope="session")
def conda_build_test_recipe_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Clone conda_build_test_recipe.

    This exposes the special dummy package "source code" used to test various git/svn/local recipe configurations.
    """
    # clone conda_build_test_recipe locally
    repo = tmp_path_factory.mktemp("conda_build_test_recipe", numbered=False)
    subprocess.run(
        ["git", "clone", "https://github.com/conda/conda_build_test_recipe", str(repo)],
        check=True,
    )
    return repo


@pytest.fixture
def conda_build_test_recipe_envvar(
    conda_build_test_recipe_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """Exposes the cloned conda_build_test_recipe as an environment variable."""
    name = "CONDA_BUILD_TEST_RECIPE_PATH"
    monkeypatch.setenv(name, str(conda_build_test_recipe_path))
    return name
