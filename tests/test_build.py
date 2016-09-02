"""
This file tests the build.py module.  It sits lower in the stack than the API tests,
and is more unit-test oriented.
"""

import copy
import os
import sys

import pytest

from conda_build import build, api
from conda_build.metadata import MetaData
from conda_build.utils import rm_rf, on_win

from .utils import testing_workdir, test_config, metadata_dir, test_metadata

prefix_tests = {"normal": os.path.sep}
if sys.platform == "win32":
    prefix_tests.update({"double_backslash": "\\\\",
                         "forward_slash": "/"})


def _write_prefix(filename, prefix, replacement):
    with open(filename, "w") as f:
        f.write(prefix.replace(os.path.sep, replacement))
        f.write("\n")


def test_find_prefix_files(testing_workdir):
    """
    Write test output that has the prefix to be found, then verify that the prefix finding
    identified the correct number of files.
    """
    # create text files to be replaced
    files = []
    for slash_style in prefix_tests:
        filename = os.path.join(testing_workdir, "%s.txt" % slash_style)
        _write_prefix(filename, testing_workdir, prefix_tests[slash_style])
        files.append(filename)

    assert len(list(build.have_prefix_files(files, testing_workdir))) == len(files)


def test_environment_creation_preserves_PATH(testing_workdir, test_config):
    ref_path = os.environ['PATH']
    build.create_env(testing_workdir, ['python'], test_config)
    assert os.environ['PATH'] == ref_path


def test_build_preserves_PATH(testing_workdir, test_config):
    m = MetaData(os.path.join(metadata_dir, 'source_git'), config=test_config)
    ref_path = os.environ['PATH']
    build.build(m, test_config)
    assert os.environ['PATH'] == ref_path


@pytest.mark.timeout(60)
@pytest.mark.skipif(on_win, reason=("Windows binary prefix replacement (for pip exes)"
                                    " not length dependent"))
def test_env_creation_with_short_prefix_does_not_deadlock(caplog):
    test_base = os.path.expanduser("~/cbtmp")
    config = api.Config(croot=test_base, anaconda_upload=False, verbose=True)
    recipe_path = os.path.join(metadata_dir, "has_prefix_files")
    fn = api.get_output_file_path(recipe_path, config=config)
    if os.path.isfile(fn):
        os.remove(fn)
    config.prefix_length = 80
    try:
        api.build(recipe_path, config=config)
        pkg_name = os.path.basename(fn).replace("-1.0-0.tar.bz2", "")
        assert not api.inspect_prefix_length(fn, 255)
        config.prefix_length = 255
        build.create_env(config.build_prefix, specs=["python", pkg_name], config=config)
    except:
        raise
    finally:
        rm_rf(test_base)
    assert 'One or more of your package dependencies needs to be rebuilt' in caplog.text()


@pytest.mark.skipif(on_win, reason=("Windows binary prefix replacement (for pip exes)"
                                    " not length dependent"))
def test_catch_openssl_legacy_short_prefix_error(caplog):
    config = api.Config(anaconda_upload=False, verbose=True, python="2.6")
    from .utils import d
    metadata = MetaData.fromdict(d, config=config)
    cmd = """
import os

prefix = os.environ['PREFIX']
fn = os.path.join(prefix, 'binary-has-prefix')

with open(fn, 'wb') as f:
    f.write(prefix.encode('utf-8') + b'\x00\x00')
 """
    metadata.meta['build']['script'] = 'python -c "{0}"'.format(cmd)

    api.build(metadata, config=config)
    assert "Falling back to legacy prefix" in caplog.text()


def test_warn_on_old_conda_build(test_config, capfd):
    installed_version = "1.21.14"

    # test with a conda-generated index first.  This is a list of Package objects,
    #    from which we just take the versions.
    build.update_index(test_config.croot, test_config)
    build.update_index(os.path.join(test_config.croot, test_config.subdir), test_config)
    build.update_index(os.path.join(test_config.croot, 'noarch'), test_config)
    index = build.get_build_index(test_config)
    # exercise the index code path, but this test is not at all deterministic.
    build.warn_on_old_conda_build(index=index)
    output, error = capfd.readouterr()

    # should see output here
    build.warn_on_old_conda_build(installed_version=installed_version,
                                  available_packages=['1.21.10', '2.0.0'])
    output, error = capfd.readouterr()
    assert "conda-build appears to be out of date. You have version " in error

    # should not see output here, because newer version has a beta tag
    build.warn_on_old_conda_build(installed_version=installed_version,
                                  available_packages=['1.21.10', '2.0.0beta2'])
    output, error = capfd.readouterr()
    assert "conda-build appears to be out of date. You have version " not in error

    # should not see output here, because newer version has a beta tag
    build.warn_on_old_conda_build(installed_version=installed_version,
                                  available_packages=['1.21.10', '2.0.0beta2'])
    output, error = capfd.readouterr()
    assert "conda-build appears to be out of date. You have version " not in error

    # should not barf on empty lists of packages; just not show anything
    #     entries with beta will be filtered out, leaving an empty list
    build.warn_on_old_conda_build(installed_version=installed_version,
                                  available_packages=['1.0.0beta'])
    output, error = capfd.readouterr()
    assert "conda-build appears to be out of date. You have version " not in error
