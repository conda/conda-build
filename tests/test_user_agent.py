# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
from conda.base.context import context, reset_context
from conda.gateways.connection.session import CondaSession
from requests import Request

from conda_build import __version__, api, plugin, render


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

    def output_yaml(*args, **kwargs):
        assert user_agent(session) == expected
        if fail:
            raise ValueError("nested call failed")
        return "recipe"

    def render_recipe(*args, **kwargs):
        if fail:
            with pytest.raises(ValueError, match="nested call failed"):
                api.output_yaml(None)
        else:
            assert api.output_yaml(None) == "recipe"
        assert user_agent(session) == expected
        return []

    monkeypatch.setattr(render, "output_yaml", output_yaml)
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
@pytest.mark.parametrize(
    "command", list(plugin.conda_subcommands()), ids=lambda c: c.name
)
@pytest.mark.filterwarnings(
    "ignore:conda_build.cli.main_develop:PendingDeprecationWarning"
)
def test_cli_user_agent(monkeypatch, command, entry_point):
    module = import_module(f"conda_build.cli.main_{command.name}")
    session = CondaSession()
    baseline = user_agent(session)
    parser_name = "get_parser" if command.name == "debug" else "parse_args"
    original = getattr(module, parser_name)

    def parse_args(*args, **kwargs):
        assert user_agent(session) == f"{baseline} conda-build/{__version__}"
        return original(*args, **kwargs)

    monkeypatch.setattr(module, parser_name, parse_args)
    monkeypatch.setattr(sys, "argv", [f"conda-{command.name}", "--help"])
    execute = command_action(command, entry_point)
    for args in (["--help"], None):
        with pytest.raises(SystemExit) as exc:
            if args is None:
                execute()
            else:
                execute(args)
        assert exc.value.code == 0
        assert user_agent(session) == baseline


@pytest.mark.parametrize("entry_point", ["plugin", "standalone"])
@pytest.mark.parametrize("fail", [False, True])
def test_cli_user_agent_return_and_exception(monkeypatch, entry_point, fail):
    module = import_module("conda_build.cli.main_render")
    command = next(c for c in plugin.conda_subcommands() if c.name == "render")
    session = CondaSession()
    baseline = user_agent(session)
    args = ["recipe"]

    def render(args):
        assert args == ["recipe"]
        assert user_agent(session) == f"{baseline} conda-build/{__version__}"
        if fail:
            raise ValueError("stop")
        return 42

    monkeypatch.setattr(module, "execute", render)
    execute = command_action(command, entry_point)
    if fail:
        with pytest.raises(ValueError, match="stop"):
            execute(args)
    else:
        assert execute(args) == 42
    assert user_agent(session) == baseline
