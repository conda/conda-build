import os

import pytest

from conda_build.conda_interface import download
from conda_build.api import convert

from .utils import testing_workdir, package_has_file, test_config

def test_convert_wheel_raises():
    with pytest.raises(RuntimeError) as exc:
        convert("some_wheel.whl")
        assert "Conversion from wheel packages" in str(exc)


def test_convert_exe_raises():
    with pytest.raises(RuntimeError) as exc:
        convert("some_wheel.exe")
        assert "cannot convert:" in str(exc)


@pytest.mark.parametrize('base_platform', ['linux', 'win', 'osx'])
def test_convert_platform_to_others(testing_workdir, base_platform):
    f = 'http://repo.continuum.io/pkgs/free/{}-64/itsdangerous-0.24-py27_0.tar.bz2'.format(base_platform)
    fn = "itsdangerous-0.24-py27_0.tar.bz2"
    download(f, fn)
    convert(fn, platforms='all', quiet=False, verbose=True)
    for platform in ['osx-64', 'win-64', 'win-32', 'linux-64', 'linux-32']:
        python_folder = 'lib/python2.7' if not platform.startswith('win') else 'Lib'
        assert package_has_file(os.path.join(platform, fn),
                                '{}/site-packages/itsdangerous.py'.format(python_folder))
