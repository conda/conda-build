import json
import os
import pytest
import re
import sys

from conda_build.render import finalize_metadata
from conda_build.conda_interface import subdir
from conda_build import api, utils

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
    assert "a-2.0-1" in outputs[0]


def test_subpackage_independent_hash(testing_metadata):
    # this recipe is creating 2 outputs.  One is the output here, a.  The other is the top-level
    #     output, implicitly created by adding the run requirement.
    testing_metadata.meta['outputs'] = [{'name': 'a', 'requirements': 'bzip2'}]
    testing_metadata.meta['requirements']['run'] = ['a']
    out_dicts_and_metadata = testing_metadata.get_output_metadata_set()
    assert len(out_dicts_and_metadata) == 2
    outputs = api.get_output_file_path([(m, None, None) for (_, m) in out_dicts_and_metadata])
    assert len(outputs) == 2
    assert outputs[0][-15:] != outputs[1][-15:]


def test_run_exports_in_subpackage(testing_metadata):
    p1 = testing_metadata.copy()
    p1.meta['outputs'] = [{'name': 'has_run_exports', 'run_exports': 'bzip2 1.0'}]
    api.build(p1, config=testing_metadata.config)[0]
    # api.update_index(os.path.dirname(output), config=testing_metadata.config)
    p2 = testing_metadata.copy()
    p2.meta['requirements']['host'] = ['has_run_exports']
    p2_final = finalize_metadata(p2)
    assert 'bzip2 1.0.*' in p2_final.meta['requirements']['run']


# @pytest.mark.serial
# def test_hash_includes_recipe_files(testing_workdir, testing_config):
#     """Hash should include all files not specifically named in any output, plus the script for
#     a given output."""
#     recipe = os.path.join(subpackage_dir, 'script_install_files')
#     outputs = api.build(recipe, config=testing_config)


def test_subpackage_variant_override(testing_config):
    recipe = os.path.join(subpackage_dir, '_variant_override')
    outputs = api.build(recipe, config=testing_config)
    # Three total:
    #    one subpackage with no deps - one output
    #    one subpackage with a python dep, and 2 python versions - 2 outputs
    assert len(outputs) == 3


@pytest.mark.skipif(sys.platform == 'darwin', reason="R has dumb binary issues, just run this on linux/win")
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


def test_git_in_output_version(testing_config):
    recipe = os.path.join(subpackage_dir, '_git_in_output_version')
    outputs = api.render(recipe, config=testing_config, finalize=False, bypass_env_check=True)
    assert len(outputs) == 1
    assert outputs[0][0].version() == '1.21.11'


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
            assert m.config.target_subdir == subdir
        elif m.name() == 'custom_subdir':
            assert m.config.target_subdir == 'linux-aarch64'
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
    outs = api.build(recipe, config=testing_config)
    for out in outs:
        about_meta = utils.package_has_file(out, 'info/about.json')
        assert about_meta
        info = json.loads(about_meta)
        if os.path.basename(out).startswith('abc'):
            assert 'summary' in info
            assert info['summary'] == 'weee'
            assert 'home' not in info
        elif os.path.basename(out).startswith('def'):
            assert 'home' in info
            assert 'summary' not in info
            assert info['home'] == 'http://not.a.url'


@pytest.mark.serial
def test_toplevel_entry_points_do_not_apply_to_subpackages(testing_config):
    recipe_dir = os.path.join(subpackage_dir, '_entry_points')
    outputs = api.build(recipe_dir, config=testing_config)
    if utils.on_win:
        script_dir = 'Scripts'
        ext = '.exe'
    else:
        script_dir = 'bin'
        ext = ''
    for out in outputs:
        fn = os.path.basename(out)
        if fn.startswith('split_package_entry_points1'):
            assert utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'pkg1', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'pkg2', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'top1', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'top2', ext))
        elif fn.startswith('split_package_entry_points2'):
            assert utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'pkg2', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'pkg1', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'top1', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'top2', ext))
        elif fn.startswith('test_split_package_entry_points'):
            # python commands will make sure that these are available.
            assert utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'top1', ext))
            assert utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'top2', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'pkg1', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'pkg2', ext))
        else:
            raise ValueError("Didn't see any of the 3 expected filenames.  Filename was {}".format(fn))


# with cb3.1, this no longer raises an error, because the subpackage hashes no
# longer depend on each other, only the external info in
# conda_build_config.yaml. Thus there is no cyclical issue here.

# def test_cyclical_exact_subpackage_pins_raises_error(testing_config):
#     recipe_dir = os.path.join(subpackage_dir, '_intradependencies_circular')
#     with pytest.raises(exceptions.RecipeError):
#         ms = api.render(recipe_dir, config=testing_config)


def test_toplevel_subpackage_exact_does_not_raise_infinite_loop_error(testing_config):
    recipe_dir = os.path.join(subpackage_dir, '_intradependencies_toplevel_circular')
    api.render(recipe_dir, config=testing_config)


def test_subpackage_hash_inputs(testing_config):
    recipe_dir = os.path.join(subpackage_dir, '_hash_inputs')
    outputs = api.build(recipe_dir, config=testing_config)
    assert len(outputs) == 2
    for out in outputs:
        if os.path.basename(out).startswith('test_subpackage'):
            assert utils.package_has_file(out, 'info/recipe/install-script.sh')
            assert utils.package_has_file(out, 'info/recipe/build.sh')
        else:
            assert utils.package_has_file(out, 'info/recipe/install-script.sh')
            assert utils.package_has_file(out, 'info/recipe/build.sh')


@pytest.mark.serial
def test_overlapping_files(testing_config, caplog):
    recipe_dir = os.path.join(subpackage_dir, '_overlapping_files')
    utils.reset_deduplicator()
    outputs = api.build(recipe_dir, config=testing_config)
    assert len(outputs) == 3
    assert sum(int("Exact overlap" in rec.message) for rec in caplog.records) == 1


def test_per_output_tests(testing_config, capfd):
    recipe_dir = os.path.join(subpackage_dir, '_per_output_tests')
    api.build(recipe_dir, config=testing_config)
    out, err = capfd.readouterr()
    # windows echoes commands, so we see the result and the command
    count = 2 if utils.on_win else 1
    assert out.count("output-level test") == count, out
    assert out.count("top-level test") == count, out


def test_pin_compatible_in_outputs(testing_config):
    recipe_dir = os.path.join(subpackage_dir, '_pin_compatible_in_output')
    m = api.render(recipe_dir, config=testing_config)[0][0]
    assert any(re.search('numpy\s*>=.*,<.*', req) for req in m.meta['requirements']['run'])


def test_output_same_name_as_top_level_does_correct_output_regex(testing_config):
    recipe_dir = os.path.join(subpackage_dir, '_output_named_same_as_top_level')
    ms = api.render(recipe_dir, config=testing_config)
    # TODO: need to decide what best behavior is for saying whether the
    # top-level build reqs or the output reqs for the similarly naemd output
    # win. I think you could have both, but it means rendering a new, extra,
    # build-only metadata in addition to all the outputs
    for m, _, _ in ms:
        if m.name() == 'ipp':
            for env in ('build', 'host', 'run'):
                assert not m.meta.get('requirements', {}).get(env)
