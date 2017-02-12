import os
import pytest

from conda_build import api

from .utils import subpackage_dir, is_valid_dir


@pytest.fixture(params=[dirname for dirname in os.listdir(subpackage_dir)
                        if is_valid_dir(subpackage_dir, dirname)])
def recipe(request):
    return os.path.join(subpackage_dir, request.param)


def test_subpackage_recipes(recipe, testing_config):
    api.build(recipe, config=testing_config)


def test_autodetect_raises_on_invalid_extension(testing_config):
    with pytest.raises(NotImplementedError):
        api.build(os.path.join(subpackage_dir, '_invalid_script_extension'), config=testing_config)


def test_rm_rf_does_not_follow_links(testing_config):
    recipe_dir = os.path.join(subpackage_dir, '_rm_rf_stays_within_prefix')
    bin_file_that_disappears = os.path.join(recipe_dir, 'bin', 'lsfm')
    if not os.path.isfile(bin_file_that_disappears):
        with open(bin_file_that_disappears, 'w') as f:
            f.write('weee')
    assert os.path.isfile(bin_file_that_disappears)
    api.build(os.path.join(recipe_dir, 'conda'), config=testing_config)
    assert os.path.isfile(bin_file_that_disappears)


def test_output_pkg_path_shows_all_subpackages(testing_metadata):
    testing_metadata.meta['outputs'] = [{'name': 'a'}, {'name': 'b'}]
    outputs = api.get_output_file_path(testing_metadata)
    assert len(outputs) == 2


def test_subpackage_version_provided(testing_metadata):
    testing_metadata.meta['outputs'] = [{'name': 'a', 'version': '2.0'}]
    outputs = api.get_output_file_path(testing_metadata)
    assert len(outputs) == 1
    assert "a-2.0-h" in outputs[0]


def test_subpackage_independent_hash(testing_metadata):
    testing_metadata.meta['outputs'] = [{'name': 'a', 'requirements': 'bzip2'}]
    testing_metadata.meta['requirements']['run'] = ['a']
    outputs = api.get_output_file_path(testing_metadata)
    assert len(outputs) == 2
    assert outputs[0][-15:] != outputs[1][-15:]
