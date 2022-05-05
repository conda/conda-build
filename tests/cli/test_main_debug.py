import io
import sys
from unittest import mock

import pytest
from pytest import CaptureFixture
from pyfakefs.fake_filesystem import FakeFilesystem

from conda_build.cli import main_debug as debug, validators as valid


@pytest.fixture(scope='session')
def main_debug_help() -> str:
    """Read what the current help message should be and return it as a fixture"""
    parser = debug.get_parser()

    with io.StringIO() as fp:
        parser.print_usage(file=fp)
        fp.seek(0)
        return fp.read()


def test_main_debug_help_message(capsys: CaptureFixture, main_debug_help: str):
    sys.argv = ['conda-debug']

    with pytest.raises(SystemExit):
        debug.main()

    captured = capsys.readouterr()
    assert main_debug_help in captured.err


def test_main_debug_file_does_not_exist(capsys: CaptureFixture):
    sys.argv = ['conda-debug', 'file-does-not-exist']

    with pytest.raises(SystemExit):
        debug.main()

    captured = capsys.readouterr()
    assert valid.get_is_conda_pkg_or_recipe_error_message() in captured.err


def test_main_debug_happy_path(fs: FakeFilesystem, capsys: CaptureFixture):
    """
    Happy path through the main_debug.main function.
    """
    with mock.patch('conda_build.api.debug') as mock_debug:
        fake_pkg_file = 'fake-conda-pkg.conda'
        fs.create_file(fake_pkg_file)
        sys.argv = ['conda-debug', fake_pkg_file]

        debug.main()

        captured = capsys.readouterr()

        assert captured.err == ''

        assert len(mock_debug.mock_calls) == 2
