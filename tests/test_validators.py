from argparse import Namespace

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

from conda_build import validators as valid

IS_CONDA_PACKAGE_OR_DIR_DATA = (
    ('aws-c-common-0.4.57-hb1e8313_1.tar.bz2', True, False, True),
    ('somedir', True, True, True),
)


@pytest.mark.parametrize('value,expected,is_dir,create', IS_CONDA_PACKAGE_OR_DIR_DATA)
def test_validate_is_conda_pkg_or_recipe_dir(
        fs: FakeFilesystem, value: str, expected: bool, is_dir: bool, create: bool
):
    if create:
        if is_dir:
            fs.create_dir(value)
        else:
            fs.create_file(value)
    name_space = Namespace()  # intentionally left empty because our validator doesn't need it

    assert valid.validate_is_conda_pkg_or_recipe_dir(value, name_space)
