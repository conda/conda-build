import io
import os.path
import sys
from unittest import mock

import pytest
from pytest import CaptureFixture

from conda_build.cli import main_debug as debug, validators as valid


@pytest.fixture(scope='module')
def main_debug_help() -> str:
    """Read what the current help message should be and return it as a fixture"""
    sys.argv = ['conda-debug']
    parser = debug.get_parser()

    with io.StringIO() as fp:
        parser.print_usage(file=fp)
        fp.seek(0)
        yield fp.read()

    sys.argv = []


def test_main_debug_help_message(capsys: CaptureFixture, main_debug_help: str):
    with pytest.raises(SystemExit):
        debug.main()

    captured = capsys.readouterr()
    assert main_debug_help in captured.err


def test_main_debug_file_does_not_exist(capsys: CaptureFixture):
    sys.argv = ['conda-debug', 'file-does-not-exist']

    with pytest.raises(SystemExit):
        debug.main()

    captured = capsys.readouterr()
    assert valid.CONDA_PKG_OR_RECIPE_ERROR_MESSAGE in captured.err


def test_main_debug_happy_path(tmpdir, capsys: CaptureFixture):
    """
    Happy path through the main_debug.main function.
    """
    with mock.patch("conda_build.api.debug") as mock_debug:
        fake_pkg_file = os.path.join(tmpdir, "fake-conda-pkg.conda")
        fp = open(fake_pkg_file, "w")
        fp.write("text")
        fp.close()
        sys.argv = ['conda-debug', fake_pkg_file]

        debug.main()

        captured = capsys.readouterr()

        assert captured.err == ''

        assert len(mock_debug.mock_calls) == 2
