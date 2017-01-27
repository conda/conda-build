import os
import pytest

from conda_build import api

from .utils import is_valid_dir, subpackage_dir


@pytest.fixture(params=[dirname for dirname in os.listdir(subpackage_dir)
                        if is_valid_dir(subpackage_dir, dirname)])
def recipe(request):
    return os.path.join(subpackage_dir, request.param)


def test_subpackage_recipes(recipe, test_config):
    api.build(recipe, config=test_config)


def test_autodetect_raises_on_invalid_extension(test_config):
    with pytest.raises(NotImplementedError):
        api.build(os.path.join(subpackage_dir, '_invalid_script_extension'), config=test_config)


def test_rm_rf_does_not_follow_links(test_config):
    recipe_dir = os.path.join(subpackage_dir, '_rm_rf_stays_within_prefix')
    bin_file_that_disappears = os.path.join(recipe_dir, 'bin', 'lsfm')
    if not os.path.isfile(bin_file_that_disappears):
        with open(bin_file_that_disappears, 'w') as f:
            f.write('weee')
    assert os.path.isfile(bin_file_that_disappears)
    api.build(os.path.join(recipe_dir, 'conda'), config=test_config)
    assert os.path.isfile(bin_file_that_disappears)
