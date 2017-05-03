import os
import pytest
import re
import sys

from conda_build import api
from conda_build.render import finalize_metadata
from conda_build.conda_interface import subdir

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
    del testing_metadata.meta['requirements']
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


def test_run_exports_in_subpackage(testing_metadata, testing_index):
    p1 = testing_metadata.copy()
    p1.meta['outputs'] = [{'name': 'has_run_exports', 'run_exports': 'bzip2 1.0'}]
    output = api.build(p1)[0]
    api.update_index(os.path.dirname(output), config=testing_metadata.config)
    p2 = testing_metadata.copy()
    p2.meta['requirements']['build'] = ['has_run_exports']
    p2.config.index = None
    p2_final = finalize_metadata(p2, None)
    assert 'bzip2 1.0' in p2_final.meta['requirements']['run']


# @pytest.mark.serial
# def test_hash_includes_recipe_files(testing_workdir, testing_config):
#     """Hash should include all files not specifically named in any output, plus the script for
#     a given output."""
#     recipe = os.path.join(subpackage_dir, 'script_install_files')
#     outputs = api.build(recipe, config=testing_config)


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
    assert len(outputs2) == 8
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


def test_git_in_output_version(testing_config):
    recipe = os.path.join(subpackage_dir, '_git_in_output_version')
    outputs = api.build(recipe, config=testing_config)
    assert len(outputs) == 1
    assert os.path.basename(outputs[0]).startswith("git_version-1.21.11-h")


def test_intradep_with_templated_output_name(testing_config):
    recipe = os.path.join(subpackage_dir, '_intradep_with_templated_output_name')
    metadata = api.render(recipe, config=testing_config)
    assert len(metadata) == 3
    expected_names = {'test_templated_subpackage_name', 'templated_subpackage_nameabc',
                      'depends_on_templated'}
    assert set((m.name() for (m, _, _) in metadata)) == expected_names


def test_output_specific_subdir(testing_config):
    recipe = os.path.join(subpackage_dir, '_output_specific_subdir')
    metadata = api.render(recipe, config=testing_config)
    assert len(metadata) == 3
    for (m, _, _) in metadata:
        if m.name() in ('default_subdir', 'default_subdir_2'):
            assert m.config.host_subdir == subdir
        elif m.name() == 'custom_subdir':
            assert m.config.host_subdir == 'linux-aarch64'
        else:
            raise AssertionError("Test for output_specific_subdir written incorrectly - "
                                 "package name not recognized")


def test_about_metadata(testing_config):
    recipe = os.path.join(subpackage_dir, '_about_metadata')
    metadata = api.render(recipe, config=testing_config)
    assert len(metadata) == 2
    for m, _, _ in metadata:
        if m.name() == 'abc':
            assert 'summary' in m.meta['about']
            assert m.meta['about']['summary'] == 'weee'
            assert 'home' not in m.meta['about']
        elif m.name() == 'def':
            assert 'home' in m.meta['about']
            assert 'summary' not in m.meta['about']
            assert m.meta['about']['home'] == 'http://not.a.url'
