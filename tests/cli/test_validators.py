from argparse import ArgumentError
from typing import Union

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

from conda_build.cli import validators as valid


@pytest.mark.parametrize(
    'file_or_folder,expected,is_dir,create',
    [
        # Happy path cases
        ('aws-c-common-0.4.57-hb1e8313_1.tar.bz2', 'aws-c-common-0.4.57-hb1e8313_1.tar.bz2', False, True),
        ('aws-c-common-0.4.57-hb1e8313_1.conda', 'aws-c-common-0.4.57-hb1e8313_1.conda', False, True),
        ('somedir', 'somedir', True, True),
        # Error case (i.e. the file or directory does not exist
        ('aws-c-common-0.4.57-hb1e8313_1.conda', False, False, False),
    ],
)
def test_validate_is_conda_pkg_or_recipe_dir(
        fs: FakeFilesystem, file_or_folder: str, expected: Union[str, bool], is_dir: bool, create: bool
):
    if create:
        if is_dir:
            fs.create_dir(file_or_folder)
        else:
            fs.create_file(file_or_folder)

    try:
        received = valid.validate_is_conda_pkg_or_recipe_dir(file_or_folder)
    except (ArgumentError, SystemExit):  # if we get these errors, we know it's not valid
        received = False

    assert received == expected
