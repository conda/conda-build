import pytest

from conda_build import conda_interface as ci


@pytest.mark.xfail(ci.conda_44, reason="Newer condas fail on CI when installed from source")
def test_get_installed_version():
    versions = ci.get_installed_version(ci.root_dir, 'conda')
    assert versions.get('conda')
    assert ci.VersionOrder(versions.get('conda'))
