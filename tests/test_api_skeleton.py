# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import ruamel.yaml

from conda_build import api
from conda_build.skeletons.pypi import (
    clean_license_name,
    convert_to_flat_list,
    get_dependencies,
    get_entry_points,
    get_home,
    get_import_tests,
    get_license_name,
    get_package_metadata,
    get_summary,
    get_tests_require,
    is_setuptools_enabled,
)
from conda_build.utils import on_win
from conda_build.version import _parse as parse_version

if TYPE_CHECKING:
    from conda_build.config import Config


SYMPY_URL = (
    "https://files.pythonhosted.org/packages/7d/23/70fa970c07f0960f7543af982d2554be805e1034b9dcee9cb3082ce80f80/sympy-1.10.tar.gz"
    "#sha256=6cf85a5cfe8fff69553e745b05128de6fc8de8f291965c63871c79701dc6efc9"
)

PYLINT_VERSION = "2.7.4"  # last version to use setup.py without setup.cfg
PYLINT_HASH_TYPE = "sha256"
PYLINT_SHA256 = "bd38914c7731cdc518634a8d3c5585951302b6e2b6de60fbb3f7a0220e21eeee"
PYLINT_BLAKE2 = "2d5b491cf9e85288c29759a6535e6009938c2141b137b27a0653e435dcbad6a2"
PYLINT_FILENAME = f"pylint-{PYLINT_VERSION}.tar.gz"
PYLINT_URL = f"https://files.pythonhosted.org/packages/{PYLINT_BLAKE2[:2]}/{PYLINT_BLAKE2[2:4]}/{PYLINT_BLAKE2[4:]}/{PYLINT_FILENAME}"


@pytest.fixture
def mock_metadata():
    return {
        "run_depends": "",
        "build_depends": "",
        "entry_points": "",
        "test_commands": "",
        "tests_require": "",
        "version": "UNKNOWN",
        "pypiurl": PYLINT_URL,
        "filename": PYLINT_FILENAME,
        "digest": [PYLINT_HASH_TYPE, PYLINT_SHA256],
        "import_tests": "",
        "summary": "",
    }


@pytest.fixture
def pylint_pkginfo():
    # Hardcoding it to avoid to use the get_pkginfo because it takes too much time
    return {
        "classifiers": [
            "Development Status :: 6 - Mature",
            "Environment :: Console",
            "Intended Audience :: Developers",
            "License :: OSI Approved :: GNU General Public License (GPL)",
            "Operating System :: OS Independent",
            "Programming Language :: Python",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.4",
            "Programming Language :: Python :: 3.5",
            "Programming Language :: Python :: 3.6",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3 :: Only",
            "Programming Language :: Python :: Implementation :: CPython",
            "Programming Language :: Python :: Implementation :: PyPy",
            "Topic :: Software Development :: Debuggers",
            "Topic :: Software Development :: Quality Assurance",
            "Topic :: Software Development :: Testing",
        ],
        "entry_points": {
            "console_scripts": [
                "pylint = pylint:run_pylint",
                "epylint = pylint:run_epylint",
                "pyreverse = pylint:run_pyreverse",
                "symilar = pylint:run_symilar",
            ]
        },
        "extras_require": {':sys_platform=="win32"': ["colorama"]},
        "home": "https://github.com/PyCQA/pylint",
        "install_requires": [
            "astroid >=2.5.2,<2.7",
            "isort >=4.2.5,<6",
            "mccabe >=0.6,<0.7",
            "toml >=0.7.1",
        ],
        "license": "GPL",
        "name": "pylint",
        "packages": [
            "pylint",
            "pylint.checkers",
            "pylint.checkers.refactoring",
            "pylint.config",
            "pylint.extensions",
            "pylint.lint",
            "pylint.message",
            "pylint.pyreverse",
            "pylint.reporters",
            "pylint.reporters.ureports",
            "pylint.testutils",
            "pylint.utils",
        ],
        "setuptools": True,
        "summary": "python code static checker",
        "tests_require": ["pytest", "pytest-benchmark"],
        "version": "2.3.1",
    }


@pytest.fixture
def pylint_metadata():
    return {
        "run_depends": [
            "astroid >=2.5.2,<2.7",
            "isort >=4.2.5,<6",
            "mccabe >=0.6,<0.7",
            "toml >=0.7.1",
        ],
        "build_depends": [
            "pip",
            "astroid >=2.5.2,<2.7",
            "isort >=4.2.5,<6",
            "mccabe >=0.6,<0.7",
            "toml >=0.7.1",
        ],
        "entry_points": [
            "pylint = pylint:run_pylint",
            "epylint = pylint:run_epylint",
            "pyreverse = pylint:run_pyreverse",
            "symilar = pylint:run_symilar",
        ],
        "test_commands": [
            "pylint --help",
            "epylint --help",
            "pyreverse --help",
            "symilar --help",
        ],
        "tests_require": ["pytest", "pytest-benchmark"],
        "version": PYLINT_VERSION,
        "pypiurl": PYLINT_URL,
        "filename": PYLINT_FILENAME,
        "digest": [PYLINT_HASH_TYPE, PYLINT_SHA256],
        "import_tests": [
            "pylint",
            "pylint.checkers",
            "pylint.checkers.refactoring",
            "pylint.config",
            "pylint.extensions",
            "pylint.lint",
            "pylint.message",
            "pylint.pyreverse",
            "pylint.reporters",
            "pylint.reporters.ureports",
            "pylint.testutils",
            "pylint.utils",
        ],
        "summary": "python code static checker",
        "packagename": "pylint",
        "home": "https://github.com/PyCQA/pylint",
        "license": "GNU General Public (GPL)",
        "license_family": "LGPL",
    }


@pytest.mark.skip("Use separate grayskull package instead of skeleton.")
@pytest.mark.parametrize(
    "prefix, repo, package, version",
    [
        ("", "pypi", "pip", "8.1.2"),
        ("r-", "cran", "acs", None),
        ("r-", "cran", "https://github.com/twitter/AnomalyDetection.git", None),
        ("perl-", "cpan", "Moo", None),
        ("", "rpm", "libX11-devel", None),
        # skeleton("luarocks") appears broken and needs work
        # https://github.com/conda/conda-build/issues/4756
        # ("lua-", "luarocks", "LuaSocket", None),
    ],
)
def test_repo(
    prefix: str,
    repo: str,
    package: str,
    version: str | None,
    tmp_path: Path,
    testing_config,
):
    api.skeletonize(
        package,
        repo,
        version=version,
        output_dir=tmp_path,
        config=testing_config,
    )

    package_name = f"{prefix}{Path(package).stem}".lower()
    assert len(
        [
            content
            for content in tmp_path.iterdir()
            if content.name.startswith(package_name) and content.is_dir()
        ]
    )


@pytest.mark.parametrize(
    "package,version",
    [
        pytest.param("sympy", "1.10", id="with version"),
        pytest.param(SYMPY_URL, None, id="with url"),
    ],
)
def test_sympy(package: str, version: str | None, tmp_path: Path, testing_config):
    api.skeletonize(
        packages=package,
        repo="pypi",
        version=version,
        config=testing_config,
        output_dir=tmp_path,
    )
    metadata = api.render(str(tmp_path / "sympy" / "meta.yaml"))[0][0]
    assert metadata.version() == "1.10"


def test_get_entry_points(pylint_pkginfo, pylint_metadata):
    pkginfo = pylint_pkginfo
    entry_points = get_entry_points(pkginfo)

    assert entry_points["entry_points"] == pylint_metadata["entry_points"]
    assert entry_points["test_commands"] == pylint_metadata["test_commands"]


def test_convert_to_flat_list():
    assert convert_to_flat_list("STRING") == ["STRING"]
    assert convert_to_flat_list([["LIST1", "LIST2"]]) == ["LIST1", "LIST2"]


def test_is_setuptools_enabled():
    assert not is_setuptools_enabled({"entry_points": "STRING"})
    assert not is_setuptools_enabled(
        {
            "entry_points": {
                "console_scripts": ["CONSOLE"],
                "gui_scripts": ["GUI"],
            }
        }
    )

    assert is_setuptools_enabled(
        {
            "entry_points": {
                "console_scripts": ["CONSOLE"],
                "gui_scripts": ["GUI"],
                "foo_scripts": ["SCRIPTS"],
            }
        }
    )


def test_get_dependencies():
    assert get_dependencies(
        ["astroid >=2.2.0,<3  #COMMENTS", "isort >=4.2.5,<5", "mccabe >=0.6,<0.7"],
        False,
    ) == ["astroid >=2.2.0,<3", "isort >=4.2.5,<5", "mccabe >=0.6,<0.7"]

    assert get_dependencies(
        ["astroid >=2.2.0,<3  #COMMENTS", "isort >=4.2.5,<5", "mccabe >=0.6,<0.7"], True
    ) == ["setuptools", "astroid >=2.2.0,<3", "isort >=4.2.5,<5", "mccabe >=0.6,<0.7"]


def test_get_import_tests(pylint_pkginfo, pylint_metadata):
    assert get_import_tests(pylint_pkginfo) == pylint_metadata["import_tests"]


def test_get_home():
    assert get_home({}) == "The package home page"
    assert get_home({}, {}) == "The package home page"
    assert get_home({"home": "HOME"}) == "HOME"
    assert get_home({}, {"home": "HOME"}) == "HOME"


def test_get_summary():
    assert get_summary({}) == "Summary of the package"
    assert get_summary({"summary": "SUMMARY"}) == "SUMMARY"
    assert get_summary({"summary": 'SUMMARY "QUOTES"'}) == r"SUMMARY \"QUOTES\""


def test_license_name(pylint_pkginfo):
    license_name = "GNU General Public License (GPL)"
    assert get_license_name(PYLINT_URL, pylint_pkginfo, True, {}) == license_name
    assert clean_license_name(license_name) == "GNU General Public (GPL)"
    assert clean_license_name("MIT License") == "MIT"


def test_get_tests_require(pylint_pkginfo, pylint_metadata):
    assert get_tests_require(pylint_pkginfo) == pylint_metadata["tests_require"]


def test_get_package_metadata(testing_config, mock_metadata, pylint_metadata):
    get_package_metadata(
        PYLINT_URL,
        mock_metadata,
        {},
        ".",
        "3.9",
        False,
        False,
        [PYLINT_URL],
        False,
        True,
        [],
        [],
        config=testing_config,
        setup_options=[],
    )
    assert mock_metadata == pylint_metadata


@pytest.mark.slow
def test_pypi_with_setup_options(tmp_path: Path, testing_config):
    # Use photutils package below because skeleton will fail unless the setup.py is given
    # the flag --offline because of a bootstrapping a helper file that
    # occurs by default.

    # Test that the setup option is used in constructing the skeleton.
    api.skeletonize(
        packages="photutils",
        repo="pypi",
        version="1.10.0",
        setup_options="--offline",
        config=testing_config,
        output_dir=tmp_path,
        extra_specs=["extension-helpers"],
    )

    # Check that the setup option occurs in bld.bat and build.sh.
    metadata = api.render(str(tmp_path / "photutils"))[0][0]
    assert "--offline" in metadata.meta["build"]["script"]


def test_pypi_pin_numpy(tmp_path: Path, testing_config: Config):
    # The package used here must have a numpy dependence for pin-numpy to have
    # any effect.
    api.skeletonize(
        packages="fasttext",
        repo="pypi",
        version="0.9.2",
        config=testing_config,
        pin_numpy=True,
        output_dir=tmp_path,
    )
    assert (tmp_path / "fasttext" / "meta.yaml").read_text().count("numpy x.x") == 2


def test_pypi_version_sorting(tmp_path: Path, testing_config: Config):
    # The package used here must have a numpy dependence for pin-numpy to have
    # any effect.
    api.skeletonize(
        packages="fasttext",
        repo="pypi",
        config=testing_config,
        output_dir=tmp_path,
    )
    metadata = api.render(str(tmp_path / "fasttext"))[0][0]
    assert parse_version(metadata.version()) >= parse_version("0.9.2")


def test_list_skeletons():
    skeletons = api.list_skeletons()
    assert set(skeletons) == {"pypi", "cran", "cpan", "luarocks", "rpm"}


def test_pypi_with_entry_points(tmp_path: Path):
    # planemo 0.75.29 dropped setup.py
    api.skeletonize(
        "planemo",
        repo="pypi",
        version="0.75.28",
        python_version="3.12",
        output_dir=tmp_path,
    )
    assert (tmp_path / "planemo").is_dir()


def test_pypi_with_version_arg(tmp_path: Path):
    # regression test for https://github.com/conda/conda-build/issues/1442
    api.skeletonize("PrettyTable", "pypi", version="0.7.2", output_dir=tmp_path)
    metadata = api.render(str(tmp_path / "prettytable"))[0][0]
    assert parse_version(metadata.version()) == parse_version("0.7.2")


@pytest.mark.slow
def test_pypi_with_extra_specs(tmp_path: Path, testing_config):
    # regression test for https://github.com/conda/conda-build/issues/1697
    # For mpi4py:
    testing_config.channel_urls.append("https://repo.anaconda.com/pkgs/free")
    extra_specs = ["cython", "mpi4py"]
    if not on_win:
        extra_specs.append("nomkl")
    api.skeletonize(
        "bigfile",
        "pypi",
        extra_specs=extra_specs,
        version="0.1.24",
        python="3.6",
        config=testing_config,
        output_dir=tmp_path,
    )
    metadata = api.render(str(tmp_path / "bigfile"))[0][0]
    assert parse_version(metadata.version()) == parse_version("0.1.24")
    assert any("cython" in req for req in metadata.meta["requirements"]["host"])
    assert any("mpi4py" in req for req in metadata.meta["requirements"]["host"])


@pytest.mark.slow
def test_pypi_with_version_inconsistency(tmp_path: Path, testing_config):
    # regression test for https://github.com/conda/conda-build/issues/189
    # For mpi4py:
    extra_specs = ["mpi4py"]
    if not on_win:
        extra_specs.append("nomkl")
    testing_config.channel_urls.append("https://repo.anaconda.com/pkgs/free")
    api.skeletonize(
        "mpi4py_test",
        "pypi",
        extra_specs=extra_specs,
        version="0.0.10",
        python="3.6",
        config=testing_config,
        output_dir=tmp_path,
    )
    metadata = api.render(str(tmp_path / "mpi4py_test"))[0][0]
    assert parse_version(metadata.version()) == parse_version("0.0.10")


def test_pypi_with_basic_environment_markers(tmp_path: Path):
    # regression test for https://github.com/conda/conda-build/issues/1974
    api.skeletonize("coconut", "pypi", version="1.2.2", output_dir=tmp_path)
    metadata = api.render(tmp_path / "coconut")[0][0]

    build_reqs = str(metadata.meta["requirements"]["host"])
    run_reqs = str(metadata.meta["requirements"]["run"])
    # should include the right dependencies for the right version
    assert "futures" not in build_reqs
    assert "futures" not in run_reqs
    assert "pygments" in build_reqs
    assert "pygments" in run_reqs


def test_setuptools_test_requirements(tmp_path: Path):
    api.skeletonize(
        packages="hdf5storage", repo="pypi", version="0.1.19", output_dir=tmp_path
    )
    metadata = api.render(str(tmp_path / "hdf5storage"))[0][0]
    assert metadata.meta["test"]["requires"] == ["nose >=1.0"]


@pytest.mark.skipif(sys.version_info < (3, 8), reason="sympy is python 3.8+")
def test_pypi_section_order_preserved(tmp_path: Path):
    """
    Test whether sections have been written in the correct order.
    """
    from conda_build.render import FIELDS
    from conda_build.skeletons.pypi import (
        ABOUT_ORDER,
        PYPI_META_STATIC,
        REQUIREMENTS_ORDER,
    )

    api.skeletonize(packages="sympy", repo="pypi", output_dir=tmp_path)
    # Since we want to check the order of items in the recipe (not whether
    # the metadata values themselves are sensible), read the file as (ordered)
    # yaml, and check the order.
    lines = [
        line
        for line in (tmp_path / "sympy" / "meta.yaml").read_text().splitlines()
        if not line.startswith("{%")
    ]

    # The loader below preserves the order of entries...
    _yaml = ruamel.yaml.YAML(typ="rt")
    recipe = _yaml.load("\n".join(lines))

    major_sections = list(recipe.keys())
    # Blank fields are omitted when skeletonizing, so prune any missing ones
    # before comparing.
    pruned_fields = [f for f in FIELDS if f in major_sections]
    assert major_sections == pruned_fields
    assert list(recipe["about"]) == ABOUT_ORDER
    assert list(recipe["requirements"]) == REQUIREMENTS_ORDER
    for k, v in PYPI_META_STATIC.items():
        assert list(v.keys()) == list(recipe[k])


@pytest.mark.skip("Use separate grayskull package instead of skeleton.")
@pytest.mark.slow
@pytest.mark.flaky(rerun=5, reruns_delay=2)
@pytest.mark.skipif(on_win, reason="shellcheck is not available on Windows")
@pytest.mark.parametrize(
    "package, repo",
    [
        ("r-rmarkdown", "cran"),
        ("Perl::Lint", "cpan"),
        ("screen", "rpm"),
    ],
)
def test_build_sh_shellcheck_clean(
    package: str, repo: str, tmp_path: Path, testing_config
):
    api.skeletonize(
        packages=package,
        repo=repo,
        output_dir=tmp_path,
        config=testing_config,
    )

    build_sh = next(
        Path(root, filename)
        for root, _, filenames in os.walk(tmp_path)
        for filename in filenames
        if filename == "build.sh"
    )
    cmd = [
        "shellcheck",
        "--enable=all",
        # SC2154: var is referenced but not assigned,
        #         see https://github.com/koalaman/shellcheck/wiki/SC2154
        "--exclude=SC2154",
        build_sh,
    ]

    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdout, _ = p.communicate()
    assert not stdout
    assert p.returncode == 0
