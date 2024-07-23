# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import re
from contextlib import nullcontext

import pytest
from conda.common.compat import on_mac, on_win

from conda_build import api
from conda_build.exceptions import CondaBuildUserError


def test_inspect_linkages():
    with pytest.raises(
        CondaBuildUserError,
        match=r"`conda inspect linkages` is only implemented on Linux and macOS",
    ) if on_win else nullcontext():
        out_string = api.inspect_linkages("python")
        assert "libncursesw" in out_string


def test_inspect_objects():
    with pytest.raises(
        CondaBuildUserError,
        match=r"`conda inspect objects` is only implemented on macOS",
    ) if not on_mac else nullcontext():
        out_string = api.inspect_objects("python")
        assert re.search("rpath:.*@loader_path", out_string)


def test_channel_installable():
    # make sure the default channel is installable as a reference
    assert api.test_installable("conda-team")
