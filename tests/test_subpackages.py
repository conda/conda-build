import os
import pytest
import re
import sys

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
    out_dicts_and_metadata = testing_metadata.get_output_metadata_set()
    outputs = api.get_output_file_path([(m, None, None) for (_, m) in out_dicts_and_metadata])
    assert len(outputs) == 2


def test_subpackage_version_provided(testing_metadata):
    testing_metadata.meta['outputs'] = [{'name': 'a', 'version': '2.0'}]
    out_dicts_and_metadata = testing_metadata.get_output_metadata_set()
    outputs = api.get_output_file_path([(m, None, None) for (_, m) in out_dicts_and_metadata])
    assert len(outputs) == 1
    assert "a-2.0-h" in outputs[0]


def test_subpackage_independent_hash(testing_metadata):
    testing_metadata.meta['outputs'] = [{'name': 'a', 'requirements': 'bzip2'}]
    testing_metadata.meta['requirements']['run'] = ['a']
    out_dicts_and_metadata = testing_metadata.get_output_metadata_set()
    assert len(out_dicts_and_metadata) == 2
    outputs = api.get_output_file_path([(m, None, None) for (_, m) in out_dicts_and_metadata])
    assert len(outputs) == 2
    assert outputs[0][-15:] != outputs[1][-15:]


def test_pin_downstream_in_subpackage(testing_metadata, testing_index):
    p1 = testing_metadata.copy()
    p1.meta['outputs'] = [{'name': 'has_pin_downstream', 'pin_downstream': 'bzip2 1.0'}]
    output = api.build(p1)[0]
    api.update_index(os.path.dirname(output), config=testing_metadata.config)
    p2 = testing_metadata.copy()
    p2.meta['requirements']['build'] = ['has_pin_downstream']
    p2.config.index = None
    p2_final = finalize_metadata(p2, None)
    assert 'bzip2 1.0' in p2_final.meta['requirements']['run']


@pytest.mark.serial
def test_hash_includes_recipe_files(testing_workdir, testing_config):
    """Hash should include all files not specifically named in any output, plus the script for
    a given output."""
    recipe = os.path.join(subpackage_dir, 'script_install_files')
    outputs = api.build(recipe, config=testing_config)


def test_subpackage_variant_override(testing_config):
    recipe = os.path.join(subpackage_dir, '_variant_override')
    outputs = api.build(recipe, config=testing_config)
    assert len(outputs) == 3


def test_intradependencies(testing_workdir, testing_config):
    # Only necessary because for conda<4.3, the `r` channel was not in `defaults`
    testing_config.channel_urls = ('r')
    testing_config.activate = True
    recipe = os.path.join(subpackage_dir, '_intradependencies')
    outputs1 = api.get_output_file_paths(recipe, config=testing_config)
    outputs1_set = set([os.path.basename(p) for p in outputs1])
    # 2 * (2 * pythons, 1 * lib, 1 * R)
    assert len(outputs1) == 8
    outputs2 = api.build(recipe, config=testing_config)
    outputs2_set = set([os.path.basename(p) for p in outputs2])
    assert outputs1_set == outputs2_set, 'pkgs differ :: get_output_file_paths()=%s but build()=%s' % (outputs1_set,
                                                                                                       outputs2_set)
    pkg_hashes = api.inspect_hash_inputs(outputs2)
    py_regex = re.compile('^python.*')
    r_regex = re.compile('^r-base.*')
    for pkg, hashes in pkg_hashes.items():
        try:
            reqs = hashes['recipe']['requirements']['build']
        except:
            reqs = []
        # Assert that:
        # 1. r-base does and python does not appear in the hash inspection for the R packages
        if re.match('^r[0-9]-', pkg):
            assert not len([m.group(0) for r in reqs for m in [py_regex.search(r)] if m])
            assert len([m.group(0) for r in reqs for m in [r_regex.search(r)] if m])
        # 2. python does and r-base does not appear in the hash inspection for the Python packages
        elif re.match('^py[0-9]-', pkg):
            assert not len([m.group(0) for r in reqs for m in [r_regex.search(r)] if m])
            assert len([m.group(0) for r in reqs for m in [py_regex.search(r)] if m])
        # 3. neither python nor r-base appear in the hash inspection for the lib packages
        elif re.match('^lib[0-9]-', pkg):
            assert not len([m.group(0) for r in reqs for m in [r_regex.search(r)] if m])
            assert not len([m.group(0) for r in reqs for m in [py_regex.search(r)] if m])
