# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import tomllib
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
from conda.base.context import context, reset_context
from conda.gateways.connection.session import CondaSession
from requests import Request

from conda_build import __version__, api, inspect_pkg, plugin, render
from conda_build.config import Config


def user_agent(session, host="example.invalid"):
    request = Request("GET", f"https://{host}/repodata.json")
    return session.prepare_request(request).headers["User-Agent"]


@pytest.mark.parametrize("worker", [False, True])
def test_api_user_agent_cached_sessions(monkeypatch, worker):
    manager = context.plugin_manager
    cached_session_headers = manager.get_cached_session_headers
    with ThreadPoolExecutor(max_workers=1) as executor:

        def prepare(host="example.invalid"):
            if worker:
                return executor.submit(
                    lambda: user_agent(CondaSession(), host)
                ).result()
            return user_agent(CondaSession(), host)

        baseline = prepare()
        assert "conda-build/" not in baseline

        def render_recipe(*args, **kwargs):
            assert manager.get_cached_session_headers is cached_session_headers
            assert prepare() == f"{baseline} conda-build/{__version__}"
            assert prepare("other.invalid") == f"{baseline} conda-build/{__version__}"
            return []

        monkeypatch.setattr(render, "render_recipe", render_recipe)
        assert api.render("recipe") == []
        assert manager.get_cached_session_headers is cached_session_headers
        assert prepare() == baseline
        assert prepare("other.invalid") == baseline


@pytest.mark.parametrize("fail", [False, True])
def test_nested_api_user_agent(monkeypatch, fail):
    session = CondaSession()
    baseline = user_agent(session)
    expected = f"{baseline} conda-build/{__version__}"

    def test_installable(channel):
        assert channel == "example.invalid"
        assert user_agent(session) == expected
        if fail:
            raise ValueError("nested call failed")
        return True

    def render_recipe(*args, **kwargs):
        if fail:
            with pytest.raises(ValueError, match="nested call failed"):
                api.test_installable("example.invalid")
        else:
            assert api.test_installable("example.invalid")
        assert user_agent(session) == expected
        return []

    monkeypatch.setattr(inspect_pkg, "test_installable", test_installable)
    monkeypatch.setattr(render, "render_recipe", render_recipe)
    assert api.render("recipe") == []
    assert user_agent(session) == baseline


@pytest.mark.parametrize("exception", [ValueError, SystemExit, KeyboardInterrupt])
def test_api_user_agent_exception_cleanup(monkeypatch, exception):
    session = CondaSession()
    baseline = user_agent(session)

    def render_recipe(*args, **kwargs):
        assert user_agent(session) == f"{baseline} conda-build/{__version__}"
        raise exception("stop")

    monkeypatch.setattr(render, "render_recipe", render_recipe)
    with pytest.raises(exception, match="stop"):
        api.render("recipe")
    assert user_agent(session) == baseline


def test_api_user_agent_survives_context_reset(monkeypatch):
    session = CondaSession()
    baseline = user_agent(session)

    def render_recipe(*args, **kwargs):
        reset_context()
        assert user_agent(session) == f"{context.user_agent} conda-build/{__version__}"
        return []

    monkeypatch.setattr(render, "render_recipe", render_recipe)
    api.render("recipe")
    assert user_agent(session) == baseline


def command_action(command, entry_point):
    if entry_point == "plugin":
        return command.action
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    name = f"conda-{command.name}"
    return EntryPoint(
        name=name, value=project["project"]["scripts"][name], group="console_scripts"
    ).load()


@pytest.mark.parametrize("entry_point", ["plugin", "standalone"])
@pytest.mark.parametrize("fail", [False, True])
def test_cli_user_agent_return_and_exception(monkeypatch, tmp_path, entry_point, fail):
    command = next(c for c in plugin.conda_subcommands() if c.name == "render")
    session = CondaSession()
    baseline = user_agent(session)
    (tmp_path / "meta.yaml").write_text(
        "package:\n  name: user-agent-test\n  version: 1.0\n"
    )

    def render_recipe(recipe, **kwargs):
        assert recipe == str(tmp_path)
        assert user_agent(session) == f"{baseline} conda-build/{__version__}"
        if fail:
            raise ValueError("stop")
        return []

    monkeypatch.setattr(render, "render_recipe", render_recipe)
    execute = command_action(command, entry_point)
    if fail:
        with pytest.raises(ValueError, match="stop"):
            execute([str(tmp_path)])
    else:
        assert execute([str(tmp_path)]) == 0
    assert user_agent(session) == baseline


def test_skeletonize_user_agent_and_keyword_arguments(monkeypatch, tmp_path):
    module = import_module("conda_build.skeletons.pypi")
    session = CondaSession()
    baseline = user_agent(session)
    output = str(tmp_path / "recipes")
    config = Config(croot=str(tmp_path / "build"))
    calls = []

    def skeletonize(packages, output_dir, version, recursive, config, extra_option):
        assert user_agent(session) == f"{baseline} conda-build/{__version__}"
        calls.append((packages, output_dir, version, recursive, extra_option))
        assert config.croot == str(tmp_path / "build")

    monkeypatch.setattr(module, "skeletonize", skeletonize)
    api.skeletonize(
        "example",
        "pypi",
        output_dir=output,
        version="1.2.3",
        recursive=True,
        config=config,
        extra_option="forwarded",
    )

    assert calls == [(["example"], output, "1.2.3", True, "forwarded")]
    assert user_agent(session) == baseline
