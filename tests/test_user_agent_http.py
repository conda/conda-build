# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest
from conda.base.context import context
from conda.gateways.connection.download import download
from conda.gateways.connection.session import get_session

import conda_build
from conda_build import api


@pytest.fixture(scope="session")
def warm_package_cache():
    # Source rendering does not need an environment or packages from a channel.
    return None


@pytest.fixture
def source_server():
    content = b"1.2.3\n"
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("User-Agent")))
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format, *args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", content, requests
        finally:
            server.shutdown()
            thread.join()


def test_render_source_user_agent(source_server, tmp_path, testing_config):
    url, content, requests = source_server
    baseline = context.user_agent
    session = get_session(f"{url}/version.txt")
    download(f"{url}/before.txt", str(tmp_path / "before.txt"))

    recipe = tmp_path / "recipe"
    recipe.mkdir()
    (recipe / "meta.yaml").write_text(
        "{% set data = load_file_regex(load_file='version.txt', regex_pattern='(.+)') %}\n"
        "package:\n"
        "  name: user-agent-source\n"
        "  version: {{ data.group(1) if data else '0' }}\n"
        "source:\n"
        f"  url: {url}/version.txt\n"
        f"  sha256: {sha256(content).hexdigest()}\n"
    )

    [(metadata, _, _)] = api.render(recipe, config=testing_config, finalize=False)

    assert metadata.version() == "1.2.3"
    assert get_session(f"{url}/after.txt") is session
    download(f"{url}/after.txt", str(tmp_path / "after.txt"))
    assert requests == [
        ("/before.txt", baseline),
        ("/version.txt", f"{baseline} conda-build/{conda_build.__version__}"),
        ("/after.txt", baseline),
    ]
