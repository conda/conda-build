import os
import pytest

from conda_build import api
from conda_build.render import finalize_metadata

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


# regression test for https://github.com/conda/conda-build/issues/1661
def test_rm_rf_does_not_remove_relative_source_package_files(testing_config, monkeypatch):
    recipe_dir = os.path.join(subpackage_dir, '_rm_rf_stays_within_prefix')
    monkeypatch.chdir(recipe_dir)
    bin_file_that_disappears = os.path.join('bin', 'lsfm')
    if not os.path.isfile(bin_file_that_disappears):
        with open(bin_file_that_disappears, 'w') as f:
            f.write('weee')
    assert os.path.isfile(bin_file_that_disappears)
    api.build('conda', config=testing_config)
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


def test_pin_downstream_in_subpackage(testing_metadata, testing_index):
    p1 = testing_metadata.copy()
    p1.meta['outputs'] = [{'name': 'has_pin_downstream', 'pin_downstream': 'bzip2 1.0'}]
    api.build(p1)
    p2 = testing_metadata.copy()
    p2.meta['requirements']['build'] = ['has_pin_downstream']
    p2.config.index = None
    p2_final = finalize_metadata(p2, None)
    assert 'bzip2 1.0' in p2_final.meta['requirements']['run']
