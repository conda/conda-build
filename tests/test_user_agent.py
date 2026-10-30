# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Event, current_thread

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
            assert prepare() == f"{baseline} conda-build/{__version__}"
            assert prepare("other.invalid") == f"{baseline} conda-build/{__version__}"
            return []

        monkeypatch.setattr(render, "render_recipe", render_recipe)
        assert api.render("recipe") == []
        assert prepare() == baseline
        assert prepare("other.invalid") == baseline


def test_nested_api_user_agent(monkeypatch):
    session = CondaSession()
    baseline = user_agent(session)
    expected = f"{baseline} conda-build/{__version__}"

    def output_yaml(*args, **kwargs):
        assert user_agent(session) == expected
        return "recipe"

    def render_recipe(*args, **kwargs):
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


@pytest.mark.parametrize(
    "command", list(plugin.conda_subcommands()), ids=lambda c: c.name
)
@pytest.mark.filterwarnings(
    "ignore:conda_build.cli.main_develop:PendingDeprecationWarning"
)
def test_cli_user_agent(monkeypatch, command):
    module = import_module(f"conda_build.cli.main_{command.name}")
    session = CondaSession()
    baseline = user_agent(session)

    def parse_args(*args, **kwargs):
        assert user_agent(session) == f"{baseline} conda-build/{__version__}"
        raise SystemExit(0)

    # debug constructs its parser directly, the other commands use parse_args.
    monkeypatch.setattr(
        module, "get_parser" if command.name == "debug" else "parse_args", parse_args
    )
    for execute in (module.execute, command.action):
        with pytest.raises(SystemExit) as exc:
            execute([])
        assert exc.value.code == 0
        assert user_agent(session) == baseline


def test_overlapping_api_calls(monkeypatch):
    session = CondaSession()
    baseline = user_agent(session)
    started = {name: Event() for name in ("first", "second")}
    finish = {name: Event() for name in started}

    def render_recipe(name, **kwargs):
        started[name].set()
        assert finish[name].wait(10)
        return []

    monkeypatch.setattr(render, "render_recipe", render_recipe)
    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            first = executor.submit(api.render, "first")
            assert started["first"].wait(10)
            second = executor.submit(api.render, "second")
            assert started["second"].wait(10)
            assert user_agent(session) == f"{baseline} conda-build/{__version__}"
            finish["first"].set()
            assert first.result(timeout=10) == []
            assert user_agent(session) == f"{baseline} conda-build/{__version__}"
            finish["second"].set()
            assert second.result(timeout=10) == []
            assert user_agent(session) == baseline
        finally:
            for event in finish.values():
                event.set()


@pytest.mark.parametrize("transition", ["entry", "exit"])
def test_inflight_session_headers(monkeypatch, transition):
    manager = context.plugin_manager
    original = manager.get_hook_results
    baseline = context.user_agent
    expected = f"{baseline} conda-build/{__version__}"
    computed, release = Event(), Event()
    manager.get_cached_session_headers.cache_clear()

    def prepare():
        return user_agent(CondaSession(), "cache-race.invalid")

    def delayed(name, **kwargs):
        result = original(name, **kwargs)
        if name == "session_headers" and current_thread().name.startswith("cache-race"):
            computed.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(manager, "get_hook_results", delayed)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="cache-race") as executor:
        future = None
        try:
            if transition == "entry":
                future = executor.submit(prepare)
                assert computed.wait(10)

            def render_recipe(*args, **kwargs):
                nonlocal future
                if transition == "entry":
                    release.set()
                    future.result(timeout=10)
                    assert prepare() == expected
                else:
                    future = executor.submit(prepare)
                    assert computed.wait(10)
                return []

            monkeypatch.setattr(render, "render_recipe", render_recipe)
            api.render("recipe")
            if transition == "exit":
                release.set()
                future.result(timeout=10)
                assert prepare() == baseline
        finally:
            release.set()
