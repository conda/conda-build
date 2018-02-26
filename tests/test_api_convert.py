import csv
import os
import json
import tarfile
import hashlib

import pytest

from conda_build.conda_interface import download
from conda_build import api
from conda_build.utils import package_has_file, on_win

from .utils import metadata_dir, assert_package_consistency


def test_convert_wheel_raises():
    with pytest.raises(RuntimeError) as exc:
        api.convert("some_wheel.whl")
        assert "Conversion from wheel packages" in str(exc)


def test_convert_exe_raises():
    with pytest.raises(RuntimeError) as exc:
        api.convert("some_wheel.exe")
        assert "cannot convert:" in str(exc)


def assert_package_paths_matches_files(package_path):
    """Ensure that info/paths.json matches info/files"""
    with tarfile.open(package_path) as t:
        files_content = t.extractfile('info/files').read().decode('utf-8')
        files_set = set(line for line in files_content.splitlines() if line)
        paths_content = json.loads(t.extractfile('info/paths.json').read().decode('utf-8'))

    for path_entry in paths_content['paths']:
        assert path_entry['_path'] in files_set
        files_set.remove(path_entry['_path'])

    assert not files_set  # Check that we've seen all the entries in files


@pytest.mark.parametrize('base_platform', ['linux', 'win', 'osx'])
@pytest.mark.parametrize('package', [('cryptography-1.8.1', '__about__.py')])
def test_show_imports(testing_workdir, base_platform, package, capfd):
    package_name, example_file = package
    platforms = ['osx-64', 'win-64', 'win-32', 'linux-64', 'linux-32']

    # skip building on the same platform as the source platform
    for platform in platforms:
        source_platform = '{}-64' .format(base_platform)
        if platform == source_platform:
            platforms.remove(platform)

    f = 'http://repo.continuum.io/pkgs/free/{}-64/{}-py36_0.tar.bz2'.format(base_platform,
                                                                            package_name)
    fn = "{}-py36_0.tar.bz2".format(package_name)
    download(f, fn)

    for platform in platforms:
        with pytest.raises(SystemExit):
            api.convert(fn, platforms=platform, show_imports=True)

        output, error = capfd.readouterr()

        # there will be four duplicate outputs since we're converting to four platforms
        assert 'import cryptography.hazmat.bindings._constant_time' in output
        assert 'import cryptography.hazmat.bindings._openssl' in output
        assert 'import cryptography.hazmat.bindings._padding' in output


@pytest.mark.parametrize('base_platform', ['linux', 'win', 'osx'])
@pytest.mark.parametrize('package', [('itsdangerous-0.24', 'itsdangerous.py')])
def test_no_imports_found(testing_workdir, base_platform, package, capfd):
    package_name, example_file = package

    f = 'http://repo.continuum.io/pkgs/free/{}-64/{}-py36_0.tar.bz2'.format(base_platform,
                                                                            package_name)
    fn = "{}-py36_0.tar.bz2".format(package_name)
    download(f, fn)

    with pytest.raises(SystemExit):
        api.convert(fn, platforms=None, show_imports=True)

    output, error = capfd.readouterr()
    assert 'No imports found.' in output


@pytest.mark.parametrize('base_platform', ['linux', 'win', 'osx'])
@pytest.mark.parametrize('package', [('cryptography-1.8.1', '__about__.py')])
def test_no_platform(testing_workdir, base_platform, package):
    package_name, example_file = package

    f = 'http://repo.continuum.io/pkgs/free/{}-64/{}-py36_0.tar.bz2'.format(base_platform,
                                                                            package_name)
    fn = "{}-py36_0.tar.bz2".format(package_name)
    download(f, fn)

    with pytest.raises(SystemExit) as e:
        api.convert(fn, platforms=None)

    assert 'Error: --platform option required for conda package conversion.' in str(e.value)


@pytest.mark.parametrize('base_platform', ['linux', 'win', 'osx'])
@pytest.mark.parametrize('package', [('cryptography-1.8.1', '__about__.py')])
def test_c_extension_error(testing_workdir, base_platform, package):
    package_name, example_file = package
    platforms = ['osx-64', 'win-64', 'win-32', 'linux-64', 'linux-32']

    # skip building on the same platform as the source platform
    for platform in platforms:
        source_platform = '{}-64' .format(base_platform)
        if platform == source_platform:
            platforms.remove(platform)

    f = 'http://repo.continuum.io/pkgs/free/{}-64/{}-py36_0.tar.bz2'.format(base_platform,
                                                                            package_name)
    fn = "{}-py36_0.tar.bz2".format(package_name)
    download(f, fn)

    for platform in platforms:
        with pytest.raises(SystemExit) as e:
            api.convert(fn, platforms=platform)

    assert ('WARNING: Package {} contains C extensions; skipping conversion. '
            'Use -f to force conversion.' .format(fn)) in str(e.value)


@pytest.mark.parametrize('base_platform', ['linux', 'win', 'osx'])
@pytest.mark.parametrize('package', [('cryptography-1.8.1', '__about__.py')])
def test_c_extension_conversion(testing_workdir, base_platform, package):
    package_name, example_file = package
    platforms = ['osx-64', 'win-64', 'win-32', 'linux-64', 'linux-32']

    # skip building on the same platform as the source platform
    for platform in platforms:
        source_platform = '{}-64' .format(base_platform)
        if platform == source_platform:
            platforms.remove(platform)

    f = 'http://repo.continuum.io/pkgs/free/{}-64/{}-py36_0.tar.bz2'.format(base_platform,
                                                                            package_name)
    fn = "{}-py36_0.tar.bz2".format(package_name)
    download(f, fn)

    for platform in platforms:
        api.convert(fn, platforms=platform, force=True)

        assert os.path.exists('{}/{}' .format(platform, fn))


@pytest.mark.parametrize('base_platform', ['linux', 'win', 'osx'])
@pytest.mark.parametrize('package', [('itsdangerous-0.24', 'itsdangerous.py'),
                                     ('py-1.4.32', 'py/__init__.py')])
def test_convert_platform_to_others(testing_workdir, base_platform, package):
    package_name, example_file = package
    subdir = '{}-64'.format(base_platform)
    f = 'http://repo.continuum.io/pkgs/free/{}/{}-py27_0.tar.bz2'.format(subdir,
                                                                         package_name)
    fn = "{}-py27_0.tar.bz2".format(package_name)
    download(f, fn)
    expected_paths_json = package_has_file(fn, 'info/paths.json')
    api.convert(fn, platforms='all', quiet=False, verbose=False)
    for platform in ['osx-64', 'win-64', 'win-32', 'linux-64', 'linux-32']:
        if subdir != platform:
            python_folder = 'lib/python2.7' if not platform.startswith('win') else 'Lib'
            package = os.path.join(platform, fn)
            assert package_has_file(package,
                                    '{}/site-packages/{}'.format(python_folder, example_file))

            if expected_paths_json:
                assert package_has_file(package, 'info/paths.json')
                assert_package_paths_matches_files(package)


@pytest.mark.skipif(on_win, reason="we create the pkg to be converted in *nix; don't run on win.")
def test_convert_from_unix_to_win_creates_entry_points(testing_config):
    recipe_dir = os.path.join(metadata_dir, "entry_points")
    fn = api.build(recipe_dir, config=testing_config)[0]
    for platform in ['win-64', 'win-32']:
        api.convert(fn, platforms=[platform], force=True)
        converted_fn = os.path.join(platform, os.path.basename(fn))
        assert package_has_file(converted_fn, "Scripts/test-script-manual-script.py")
        assert package_has_file(converted_fn, "Scripts/test-script-manual.exe")
        script_contents = package_has_file(converted_fn, "Scripts/test-script-setup-script.py")
        assert script_contents
        assert "Test script setup" in script_contents.decode()
        bat_contents = package_has_file(converted_fn, "Scripts/test-script-setup.exe")
        assert bat_contents
        assert_package_consistency(converted_fn)
        paths_content = json.loads(package_has_file(converted_fn, 'info/paths.json').decode())

        # Check the validity of the sha of the converted scripts
        for f in paths_content.values():
            if f['_path'].startswith('Scripts/') and f['_path'].endswith('-script.py'):
                script_content = package_has_file(converted_fn, f['_path'])
                assert f['sha256'] == hashlib.sha256(script_content).hexdigest()

        paths_list = {f['_path'] for f in paths_content['paths']}
        files = {p.decode() for p in package_has_file(converted_fn, 'info/files').splitlines()}
        assert files == paths_list

        index = json.loads(package_has_file(converted_fn, 'info/index.json').decode())
        assert index['subdir'] == platform

        has_prefix_files = package_has_file(converted_fn, "info/has_prefix").decode()
        fieldnames = ['prefix', 'type', 'path']
        csv_dialect = csv.Sniffer().sniff(has_prefix_files)
        csv_dialect.lineterminator = '\n'
        has_prefix_files = csv.DictReader(has_prefix_files.splitlines(), fieldnames=fieldnames,
                                          dialect=csv_dialect)
        has_prefix_files = {d['path']: d for d in has_prefix_files}
        assert len(has_prefix_files) == 4
        assert 'Scripts/test-script-script.py' in has_prefix_files
        assert 'Scripts/test-script-setup-script.py' in has_prefix_files
        assert 'Scripts/test-script-manual-script.py' in has_prefix_files
        assert 'Scripts/test-script-manual-postfix-script.py' in has_prefix_files


@pytest.mark.parametrize('base_platform', ['linux', 'win', 'osx'])
@pytest.mark.parametrize('package', [('anaconda-4.4.0', 'version.txt')])
def test_convert_dependencies(testing_workdir, base_platform, package):
    package_name, example_file = package
    subdir = '{}-64'.format(base_platform)
    f = 'http://repo.continuum.io/pkgs/free/{}/{}-np112py36_0.tar.bz2'.format(subdir,
                                                                              package_name)
    fn = "{}-np112py36_0.tar.bz2".format(package_name)
    download(f, fn)

    dependencies = ['numpy 1.7.1 py36_0', 'cryptography 1.7.0 py36_0']
    expected_paths_json = package_has_file(fn, 'info/paths.json')
    api.convert(fn, platforms='all', dependencies=dependencies, quiet=False, verbose=False)
    for platform in ['osx-64', 'win-64', 'win-32', 'linux-64', 'linux-32']:
        if platform != subdir:
            python_folder = 'lib/python3.6' if not platform.startswith('win') else 'Lib'
            package = os.path.join(platform, fn)
            assert package_has_file(package,
                                    '{}/{}'.format(python_folder, example_file))

            with tarfile.open(package) as t:
                info = json.loads(t.extractfile('info/index.json').read().decode('utf-8'))

                assert 'numpy 1.7.1 py36_0' in info['depends']
                assert 'numpy 1.12.1 py36_0' not in info['depends']
                assert 'cryptography 1.7.0 py36_0' in info['depends']
                assert 'cryptography 1.8.1 py36_0' not in info['depends']

            if expected_paths_json:
                assert package_has_file(package, 'info/paths.json')
                assert_package_paths_matches_files(package)


@pytest.mark.parametrize('base_platform', ['linux', 'win', 'osx'])
@pytest.mark.parametrize('package', [('anaconda-4.4.0', 'version.txt')])
def test_convert_no_dependencies(testing_workdir, base_platform, package):
    package_name, example_file = package
    subdir = '{}-64'.format(base_platform)
    f = 'http://repo.continuum.io/pkgs/free/{}/{}-np112py36_0.tar.bz2'.format(subdir,
                                                                              package_name)
    fn = "{}-np112py36_0.tar.bz2".format(package_name)
    download(f, fn)

    expected_paths_json = package_has_file(fn, 'info/paths.json')
    api.convert(fn, platforms='all', dependencies=None, quiet=False, verbose=False)
    for platform in ['osx-64', 'win-64', 'win-32', 'linux-64', 'linux-32']:
        if platform != subdir:
            python_folder = 'lib/python3.6' if not platform.startswith('win') else 'Lib'
            package = os.path.join(platform, fn)
            assert package_has_file(package,
                                    '{}/{}'.format(python_folder, example_file))

            with tarfile.open(package) as t:
                info = json.loads(t.extractfile('info/index.json').read().decode('utf-8'))

                assert 'numpy 1.12.1 py36_0' in info['depends']
                assert 'cryptography 1.8.1 py36_0' in info['depends']

            if expected_paths_json:
                assert package_has_file(package, 'info/paths.json')
                assert_package_paths_matches_files(package)


@pytest.mark.parametrize('base_platform', ['linux', 'win', 'osx'])
@pytest.mark.parametrize('package', [('anaconda-4.4.0', 'version.txt')])
def test_skip_conversion(testing_workdir, base_platform, package, capfd):
    package_name, example_file = package
    source_plat_arch = '{}-64' .format(base_platform)

    f = 'http://repo.continuum.io/pkgs/free/{}-64/{}-np112py36_0.tar.bz2'.format(base_platform,
                                                                            package_name)
    fn = "{}-np112py36_0.tar.bz2".format(package_name)
    download(f, fn)

    api.convert(fn, platforms=source_plat_arch, dependencies=None, quiet=False, verbose=False)

    output, error = capfd.readouterr()

    skip_message = ("Source platform '{}' and target platform '{}' are identical. "
                    "Skipping conversion.\n"
                    .format(source_plat_arch, source_plat_arch))

    package = os.path.join(source_plat_arch, fn)

    assert skip_message in output
    assert not os.path.exists(package)
