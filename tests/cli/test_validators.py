import os
from argparse import ArgumentError
from typing import Union

import pytest

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
    file_or_folder: str, expected: Union[str, bool], is_dir: bool, create: bool, tmpdir
):
    if create:
        file_or_folder = os.path.join(tmpdir, file_or_folder)
        expected = os.path.join(tmpdir, expected)
        if is_dir:
            os.mkdir(file_or_folder)
        else:
            with open(file_or_folder, "w") as fp:
                fp.write("test")

    try:
        received = valid.validate_is_conda_pkg_or_recipe_dir(file_or_folder)
    except (ArgumentError, SystemExit):  # if we get these errors, we know it's not valid
        received = False

    assert received == expected
