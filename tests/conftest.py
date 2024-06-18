# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import requests
from conda.common.compat import on_mac, on_win
from conda_index.api import update_index
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
)
from conda_build.metadata import MetaData
from conda_build.utils import check_call_env, copy_into, prepend_bin_path
from conda_build.variants import get_default_variant

if TYPE_CHECKING:
    from typing import Iterator

    from pytest import Config as PytestConfig
    from pytest import TempPathFactory


@pytest.hookimpl
def pytest_report_header(config: PytestConfig):
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
def conda_build_test_recipe_path(tmp_path_factory: TempPathFactory) -> Path:
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
    monkeypatch: MonkeyPatch,
) -> str:
    """Exposes the cloned conda_build_test_recipe as an environment variable."""
    name = "CONDA_BUILD_TEST_RECIPE_PATH"
    monkeypatch.setenv(name, str(conda_build_test_recipe_path))
    return name


@pytest.fixture(scope="session")
def empty_channel(tmp_path_factory: TempPathFactory) -> Path:
    """Create a temporary, empty conda channel."""
    channel = tmp_path_factory.mktemp("empty_channel", numbered=False)
    update_index(channel)
    return channel


MACOSX_SDKS = {
    "13.3": {
        "sha256": "71ae3a78ab1be6c45cf52ce44cb29a3cc27ed312c9f7884ee88e303a862a1404",
        "url": "https://github.com/alexey-lysiuk/macos-sdk/releases/download/13.3/MacOSX13.3.tar.xz",
    },
    "12.3": {
        "sha256": "91c03be5399be04d8f6b773da13045525e01298c1dfff273b4e1f1e904ee5484",
        "url": "https://github.com/alexey-lysiuk/macos-sdk/releases/download/12.3/MacOSX12.3.tar.xz",
    },
    "11.3": {
        "sha256": "d6604578f4ee3090d1c3efce1e5c336ecfd7be345d046c729189d631ea3b8ec6",
        "url": "https://github.com/alexey-lysiuk/macos-sdk/releases/download/11.3/MacOSX11.3.tar.bz2",
    },
    "11.1": {
        "sha256": "68797baaacb52f56f713400de306a58a7ca00b05c3dc6d58f0a8283bcac721f8",
        "url": "https://github.com/phracker/MacOSX-SDKs/releases/download/11.3/MacOSX11.1.sdk.tar.xz",
    },
    "11.0": {
        "sha256": "d3feee3ef9c6016b526e1901013f264467bb927865a03422a9cb925991cc9783",
        "url": "https://github.com/phracker/MacOSX-SDKs/releases/download/11.3/MacOSX11.0.sdk.tar.xz",
    },
    "10.15": {
        "sha256": "bb548125ebf5cf4ae6c80d226f40ad39e155564ca78bc00554a2e84074d0180e",
        "url": "https://github.com/alexey-lysiuk/macos-sdk/releases/download/10.15/MacOSX10.15.tar.bz2",
    },
    "10.14": {
        "sha256": "e0a9747ae9838aeac70430c005f9757587aa055c690383d91165cf7b4a80401d",
        "url": "https://github.com/alexey-lysiuk/macos-sdk/releases/download/10.14/MacOSX10.14.tar.bz2",
    },
    "10.13": {
        "sha256": "27943fb63c35e262b2da1cb4cc60d7427702a40caf20ec15c9d773919c6e409b",
        "url": "https://github.com/alexey-lysiuk/macos-sdk/releases/download/10.13/MacOSX10.13.tar.bz2",
    },
    "10.12": {
        "sha256": "fd4e1151056f34f76b5930cb45b9cd859414acbc3f6529c0c0ecaaf2566823ff",
        "url": "https://github.com/alexey-lysiuk/macos-sdk/releases/download/10.12/MacOSX10.12.tar.bz2",
    },
    "10.11": {
        "sha256": "2e28c2eeb716236d89ea3d12a228e291bdab875c50f013a909f3592007f21484",
        "url": "https://github.com/alexey-lysiuk/macos-sdk/releases/download/10.11/MacOSX10.11.tar.bz2",
    },
    "10.10": {
        "sha256": "9fae9028802bca2c2b953f1dcc51c71382eeab4ca28644a45bcdf072b56950b9",
        "url": "https://github.com/alexey-lysiuk/macos-sdk/releases/download/10.10/MacOSX10.10.tar.bz2",
    },
    "10.9": {
        "sha256": "a119c169b39800b4646beed55ad450bbcdd01c7209ced71872f7ba644f7a5dee",
        "url": "https://github.com/alexey-lysiuk/macos-sdk/releases/download/10.9/MacOSX10.9.tar.bz2",
    },
}


@pytest.fixture(scope="session")
def get_macosx_sdk(
    pytestconfig: PytestConfig,
    tmp_path_factory: TempPathFactory,
) -> str | None:
    if not on_mac:
        return None

    macosx_sdk_version = os.getenv("MACOSX_SDK_VERSION") or "10.9"
    if os.getenv("CI"):
        cache = Path.home() / "macosx_sdks"
        cache.mkdir(exist_ok=True)
    else:
        cache = pytestconfig.cache.mkdir("macosx_sdks")
    cached_sdk = cache / f"MacOSX{macosx_sdk_version}.sdk"

    if not cached_sdk.exists():
        try:
            sdk = MACOSX_SDKS[macosx_sdk_version]
        except KeyError:
            # KeyError: unknown MacOSX SDK version
            raise ValueError(f"Unknown MacOSX SDK version: {macosx_sdk_version}")

        # download SDK and compute SHA 256
        url = sdk["url"]
        tarball_sdk = cache / url.rsplit("/", 1)[-1]
        if not tarball_sdk.exists():
            with requests.get(url, stream=True) as response:
                response.raise_for_status()

                with tarball_sdk.open("wb") as path:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            path.write(chunk)

        # verify SDK's SHA 256
        expected_sha256 = sdk["sha256"]
        computed_sha256 = hashlib.sha256()
        with tarball_sdk.open("rb") as path:
            for chunk in iter(lambda: path.read(8192), b""):
                computed_sha256.update(chunk)
        if computed_sha256.hexdigest() != expected_sha256:
            tarball_sdk.remove()
            raise ValueError("SHA 256 mismatch for downloaded SDK")

        # extract the SDK
        tarfile.open(tarball_sdk).extractall(cached_sdk)

    with MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("CONDA_BUILD_SYSROOT", str(cached_sdk))
        monkeypatch.setenv("MACOSX_DEPLOYMENT_TARGET", macosx_sdk_version)
        return macosx_sdk_version
