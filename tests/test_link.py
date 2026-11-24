# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import importlib
import json
import sys
import sysconfig
from os.path import join, normpath
from pathlib import Path

import pytest

from conda_build import _link


@pytest.fixture
def reload_link():
    yield
    importlib.reload(_link)  # restore real globals after each test


def test_site_packages_matches_sysconfig(reload_link):
    importlib.reload(_link)
    expected = (
        Path(sysconfig.get_path("purelib")).relative_to(normpath(sys.prefix)).as_posix()
    )
    assert _link.SITE_PACKAGES == expected
    assert _link.BIN_DIR == join(
        normpath(sys.prefix), "Scripts" if sys.platform == "win32" else "bin"
    )


def test_site_packages_py315_windows(reload_link, monkeypatch):
    monkeypatch.setattr(_link.sys, "platform", "win32")
    monkeypatch.setattr(
        _link.sysconfig,
        "get_path",
        lambda name: str(Path(_link.sys.prefix) / "lib" / "python" / "site-packages"),
    )
    importlib.reload(_link)
    assert _link.SITE_PACKAGES == "lib/python/site-packages"
    assert _link.BIN_DIR.endswith("Scripts")


def test_site_packages_free_threaded(reload_link, monkeypatch):
    monkeypatch.setattr(
        _link.sysconfig,
        "get_path",
        lambda name: str(
            Path(_link.sys.prefix) / "lib" / "python3.14t" / "site-packages"
        ),
    )
    importlib.reload(_link)
    assert _link.SITE_PACKAGES == "lib/python3.14t/site-packages"


def test_generated_link_runs_standalone(tmp_path, monkeypatch):
    # stage a fake prefix: link.py + site-packages payload + conda-meta
    link_py = tmp_path / "link.py"
    data = {
        "dist": "x-0-0",
        "site-packages": ["pkg/mod.py"],
        "python-scripts": [],
        "Examples": [],
    }
    payload = tmp_path / "site-packages" / "pkg" / "mod.py"
    payload.parent.mkdir(parents=True)
    payload.write_text("value = 1\n")
    (tmp_path / "conda-meta").mkdir()
    source = (
        Path(_link.__file__)
        .read_text()
        .replace("from __future__ import annotations\n", "")
    )
    link_py.write_text("DATA = " + json.dumps(data) + "\n## END DATA\n\n" + source)

    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr(
        sysconfig,
        "get_path",
        lambda _name: str(Path(tmp_path) / _link.SITE_PACKAGES),
    )
    exec(
        compile(link_py.read_text(), str(link_py), "exec"),
        {"__name__": "__main__", "__file__": str(link_py)},
    )

    placed = Path(join(str(tmp_path), _link.SITE_PACKAGES, "pkg", "mod.py"))
    assert placed.read_text() == "value = 1\n"
    manifest = (tmp_path / "conda-meta" / "x-0-0.files").read_text().splitlines()
    assert f"{_link.SITE_PACKAGES}/pkg/mod.py" in manifest


def test_generated_link_has_no_conda_build_import():
    source = Path(_link.__file__).read_text()
    assert "from ." not in source
    assert "from conda_build" not in source
    assert "import conda_build" not in source
