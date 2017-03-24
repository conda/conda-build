import contextlib
import os
import sys
import shlex


import pytest

from conda_build.conda_interface import PY3
from conda_build.metadata import MetaData
from conda_build.utils import on_win

thisdir = os.path.dirname(os.path.realpath(__file__))
metadata_dir = os.path.join(thisdir, "test-recipes/metadata")
subpackage_dir = os.path.join(thisdir, "test-recipes/split-packages")
fail_dir = os.path.join(thisdir, "test-recipes/fail")


def is_valid_dir(parent_dir, dirname):
    valid = os.path.isdir(os.path.join(parent_dir, dirname))
    valid &= not dirname.startswith("_")
    valid &= ('osx_is_app' != dirname or sys.platform == "darwin")
    return valid


def add_mangling(filename):
    if PY3:
        filename = os.path.splitext(filename)[0] + '.cpython-{0}{1}.py'.format(
            sys.version_info.major, sys.version_info.minor)
        filename = os.path.join(os.path.dirname(filename), '__pycache__',
                                os.path.basename(filename))
    return filename + 'c'


def assert_package_consistency(package_path):
    """Assert internal consistency of package

    - All files in info/files are included in package
    - All files in info/has_prefix is included in info/files
    - All info in paths.json is correct (not implemented - currently fails for conda-convert)

    Return nothing, but raise RuntimeError if inconsistencies are found.
    """
    import tarfile
    try:
        with tarfile.open(package_path) as t:
            # Read info from tar file
            member_list = t.getnames()
            files = t.extractfile('info/files').read().decode('utf-8')
            # Read info/has_prefix if present
            if 'info/has_prefix' in member_list:
                has_prefix_present = True
                has_prefix = t.extractfile('info/has_prefix').read().decode('utf-8')
            else:
                has_prefix_present = False
    except tarfile.ReadError:
        raise RuntimeError("Could not extract metadata from %s. "
                           "File probably corrupt." % package_path)
    errors = []
    member_set = set(member_list)  # The tar format allows duplicates in member_list
    # Read info from info/files
    file_list = files.splitlines()
    file_set = set(file_list)
    # Check that there are no duplicates in info/files
    if len(file_list) != len(file_set):
        errors.append("Duplicate files in info/files in %s" % package_path)
    # Compare the contents of files and members
    unlisted_members = member_set.difference(file_set)
    missing_members = file_set.difference(member_set)
    # Find any unlisted members outside the info directory
    missing_files = [m for m in unlisted_members if not m.startswith('info/')]
    if len(missing_files) > 0:
        errors.append("The following package files are not listed in "
                           "info/files: %s" % ', '.join(missing_files))
    # Find any files missing in the archive
    if len(missing_members) > 0:
        errors.append("The following files listed in info/files are missing: "
                           "%s" % ', '.join(missing_members))
    # Find any files in has_prefix that are not present in files
    if has_prefix_present:
        prefix_path_list = []
        for line in has_prefix.splitlines():
            # (parsing from conda/gateways/disk/read.py::read_has_prefix() in conda repo)
            parts = tuple(x.strip('"\'') for x in shlex.split(line, posix=False))
            if len(parts) == 1:
                prefix_path_list.append(parts[0])
            elif len(parts) == 3:
                prefix_path_list.append(parts[2])
            else:
                errors.append("Invalid has_prefix file in package: %s" % package_path)
        prefix_path_set = set(prefix_path_list)
        if len(prefix_path_list) != len(prefix_path_set):
            errors.append("Duplicate files in info/has_prefix in %s" % package_path)
        prefix_not_in_files = prefix_path_set.difference(file_set)
        if len(prefix_not_in_files) > 0:
            errors.append("The following files listed in info/has_prefix are missing "
                          "from info/files: %s" % ', '.join(prefix_not_in_files))

    # Assert that no errors are detected
    assert len(errors) == 0, '\n'.join(errors)


@contextlib.contextmanager
def put_bad_conda_on_path(testing_workdir):
    path_backup = os.environ['PATH']
    # it is easier to add an intentionally bad path than it is to try to scrub any existing path
    os.environ['PATH'] = os.pathsep.join([testing_workdir, os.environ["PATH"]])

    exe_name = 'conda.bat' if on_win else 'conda'
    out_exe = os.path.join(testing_workdir, exe_name)
    with open(out_exe, 'w') as f:
        f.write("exit 1")
    st = os.stat(out_exe)
    os.chmod(out_exe, st.st_mode | 0o111)
    try:
        yield
    except:
        raise
    finally:
        os.environ['PATH'] = path_backup


def get_noarch_python_meta(meta):
    d = meta.meta
    d['build']['noarch'] = "python"
    return MetaData.fromdict(d, config=meta.config)


@pytest.fixture(autouse=True)
def skip_serial(request):
    if (request.node.get_marker('serial') and
            getattr(request.config, 'slaveinput', {}).get('slaveid', 'local') != 'local'):
        # under xdist and serial
        pytest.skip('serial')
