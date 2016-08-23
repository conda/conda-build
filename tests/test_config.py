import os
import sys

import pytest

from conda_build.config import Config
from conda_build.utils import on_win


@pytest.fixture
def config():
    """a tiny bit of a fixture to save us from manually creating a new Config each test"""
    return Config()


def test_set_build_id(config):
    build_id = "test123"
    config.build_id = build_id
    # windows always uses the short prefix due to its limitation of 260 char paths
    if sys.platform == 'win32':
        assert config.build_prefix == os.path.join(config.croot, build_id, "b_env")
    else:
        long_prefix = os.path.join(config.croot, build_id,
                                   "_b_env" + "_placehold" * 25)[:config.prefix_length]
        assert config.build_prefix == long_prefix


@pytest.mark.skipif(on_win, reason="Windows uses only the short prefix")
def test_long_build_prefix_length(config):
    config.use_long_build_prefix = True
    config.prefix_length = 80
    assert len(config.build_prefix) == config.prefix_length
    config.prefix_length = 255
    assert len(config.build_prefix) == config.prefix_length


def test_build_id_at_end_of_long_build_prefix(config):
    config.use_long_build_prefix = True
    build_id = 'test123'
    config.build_id = build_id
    assert build_id in config.build_prefix
