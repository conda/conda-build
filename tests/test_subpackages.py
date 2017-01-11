import os
import pytest

from conda_build import api

from .utils import test_config, testing_workdir, is_valid_dir, subpackage_dir

@pytest.fixture(params=[dirname for dirname in os.listdir(subpackage_dir)
                        if is_valid_dir(subpackage_dir, dirname)])
def recipe(request):
    return os.path.join(subpackage_dir, request.param)


def test_subpackage_recipes(recipe, test_config):
    api.build(recipe, config=test_config)


def test_autodetect_raises_on_invalid_extension(test_config):
    with pytest.raises(NotImplementedError):
        api.build(os.path.join(subpackage_dir, '_invalid_script_extension'), config=test_config)


# def test_all_subpackages_uploaded():
#     raise NotImplementedError
