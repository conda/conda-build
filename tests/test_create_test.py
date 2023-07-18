# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conda_build.create_test import (
    create_lua_files,
    create_pl_files,
    create_py_files,
    create_r_files,
)


@pytest.mark.parametrize(
    "name,imports,expected,unexpected",
    [
        pytest.param(
            "name",
            ["time", "datetime"],
            {".py": {"import time", "import datetime"}},
            {".r", ".pl", ".lua"},
            id="implicit Python imports",
        ),
        pytest.param(
            "r-name",
            [{"lang": "python", "imports": ["time", "datetime"]}],
            {".r": set(), ".py": {"import time", "import datetime"}},
            {".pl", ".lua"},
            id="explicit Python imports",
        ),
        pytest.param(
            "r-name",
            [
                {"lang": "python", "imports": ["time"]},
                {"lang": "python", "imports": ["datetime"]},
            ],
            {".r": set(), ".py": {"import time", "import datetime"}},
            {".pl", ".lua"},
            id="multiple explicit Python imports",
        ),
        pytest.param(
            "r-name",
            ["r-time", "r-datetime"],
            {".r": {"library(r-time)", "library(r-datetime)"}},
            {".py", ".pl", ".lua"},
            id="implicit R imports",
        ),
        pytest.param(
            "perl-name",
            [{"lang": "r", "imports": ["r-time", "r-datetime"]}],
            {".pl": set(), ".r": {"library(r-time)", "library(r-datetime)"}},
            {".py", ".lua"},
            id="explicit R imports",
        ),
        # unsupported syntax, why?
        # pytest.param(
        #     "perl-name",
        #     [
        #         {"lang": "r", "imports": ["r-time"]},
        #         {"lang": "r", "imports": ["r-datetime"]},
        #     ],
        #     {".r": {"library(r-time)", "library(r-datetime)"}},
        #     {".py", ".pl", ".lua"},
        #     id="multiple explicit R imports",
        # ),
        pytest.param(
            "perl-name",
            ["perl-time", "perl-datetime"],
            {".pl": {"use perl-time;", "use perl-datetime;"}},
            {".py", ".r", ".lua"},
            id="implicit Perl imports",
        ),
        pytest.param(
            "lua-name",
            [{"lang": "perl", "imports": ["perl-time", "perl-datetime"]}],
            {".lua": set(), ".pl": {"use perl-time;", "use perl-datetime;"}},
            {".py", ".r"},
            id="explicit Perl imports",
        ),
        # unsupported syntax, why?
        # pytest.param(
        #     "lua-name",
        #     [
        #         {"lang": "perl", "imports": ["perl-time"]},
        #         {"lang": "perl", "imports": ["perl-datetime"]},
        #     ],
        #     {".pl": {"use perl-time;", "use perl-datetime;"}},
        #     {".py", ".r", ".lua"},
        #     id="multiple explicit Perl imports",
        # ),
        pytest.param(
            "lua-name",
            ["lua-time", "lua-datetime"],
            {".lua": {'require "lua-time"', 'require "lua-datetime"'}},
            {".py", ".r", ".pl"},
            id="implicit Lua imports",
        ),
        # why is this test different from the other explicit imports?
        pytest.param(
            "name",
            [{"lang": "lua", "imports": ["lua-time", "lua-datetime"]}],
            {".lua": {'require "lua-time"', 'require "lua-datetime"'}},
            {".py", ".r", ".pl"},
            id="explicit Lua imports",
        ),
        # unsupported syntax, why?
        # pytest.param(
        #     "name",
        #     [
        #         {"lang": "lua", "imports": ["lua-time"]},
        #         {"lang": "lua", "imports": ["lua-datetime"]},
        #     ],
        #     {".lua": {'require "lua-time"', 'require "lua-datetime"'}},
        #     {".py", ".r", ".pl"},
        #     id="multiple explicit Lua imports",
        # ),
    ],
)
def test_create_run_test(
    name: str,
    imports: Any,
    expected: dict[str, set[str]],
    unexpected: set[str],
    testing_metadata,
):
    testing_metadata.meta["package"]["name"] = name
    testing_metadata.meta["test"]["imports"] = imports
    create_py_files(testing_metadata, testing_metadata.config.test_dir)
    create_r_files(testing_metadata, testing_metadata.config.test_dir)
    create_pl_files(testing_metadata, testing_metadata.config.test_dir)
    create_lua_files(testing_metadata, testing_metadata.config.test_dir)

    # assert expected test file exists
    for ext, tests in expected.items():
        test_file = Path(testing_metadata.config.test_dir, "run_test").with_suffix(ext)
        assert test_file.is_file()

        # ensure all tests (for this language/ext) are present in the test file
        assert tests <= set(filter(None, test_file.read_text().split("\n")))

    # assert unexpected test files do not exist
    for ext in unexpected:
        test_file = Path(testing_metadata.config.test_dir, "run_test").with_suffix(ext)
        assert not test_file.exists()
