# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import re
import sys

import pytest

from conda_build import api


def test_inspect_linkages():
    if sys.platform == "win32":
        with pytest.raises(SystemExit) as exc:
            out_string = api.inspect_linkages("python")
            assert "conda inspect linkages is only implemented in Linux and OS X" in exc
    else:
        out_string = api.inspect_linkages("python")
        assert "libncursesw" in out_string


def test_inspect_objects():
    if sys.platform != "darwin":
        with pytest.raises(SystemExit) as exc:
            out_string = api.inspect_objects("python")
            assert "conda inspect objects is only implemented in OS X" in exc
    else:
        out_string = api.inspect_objects("python")
        assert re.search("rpath:.*@loader_path", out_string)


def test_channel_installable():
    # make sure the default channel is installable as a reference
    assert api.test_installable("conda-team")
