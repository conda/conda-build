import os

import pytest

from conda_build.conda_interface import download
from conda_build import api
from conda_build.utils import package_has_file

from .utils import testing_workdir, test_config, on_win, metadata_dir, assert_package_consistency

def test_convert_wheel_raises():
    with pytest.raises(RuntimeError) as exc:
        api.convert("some_wheel.whl")
        assert "Conversion from wheel packages" in str(exc)


def test_convert_exe_raises():
    with pytest.raises(RuntimeError) as exc:
        api.convert("some_wheel.exe")
        assert "cannot convert:" in str(exc)


@pytest.mark.serial
@pytest.mark.parametrize('base_platform', ['linux', 'win', 'osx'])
def test_convert_platform_to_others(testing_workdir, base_platform):
    f = 'http://repo.continuum.io/pkgs/free/{}-64/itsdangerous-0.24-py27_0.tar.bz2'.format(base_platform)
    fn = "itsdangerous-0.24-py27_0.tar.bz2"
    download(f, fn)
    api.convert(fn, platforms='all', quiet=False, verbose=True)
    for platform in ['osx-64', 'win-64', 'win-32', 'linux-64', 'linux-32']:
        python_folder = 'lib/python2.7' if not platform.startswith('win') else 'Lib'
        assert package_has_file(os.path.join(platform, fn),
                                '{}/site-packages/itsdangerous.py'.format(python_folder))


@pytest.mark.serial
@pytest.mark.skipif(on_win, reason="we create the package to be converted in *nix, so don't run on win.")
def test_convert_from_unix_to_win_creates_entry_points(test_config):
    recipe_dir = os.path.join(metadata_dir, "entry_points")
    fn = api.get_output_file_path(recipe_dir, config=test_config)
    api.build(recipe_dir, config=test_config)
    for platform in ['win-64', 'win-32']:
        api.convert(fn, platforms=[platform], force=True)
        converted_fn = os.path.join(platform, os.path.basename(fn))
        assert package_has_file(converted_fn, "Scripts/test-script-manual-script.py")
        assert package_has_file(converted_fn, "Scripts/test-script-manual.bat")
        assert package_has_file(converted_fn, "Scripts/test-script-setup-script.py")
        assert package_has_file(converted_fn, "Scripts/test-script-setup.bat")
        assert_package_consistency(converted_fn)
