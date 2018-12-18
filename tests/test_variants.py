from collections import OrderedDict
import os
import json
import re
import sys

import pytest
import yaml

from conda_build import api, exceptions, variants
from conda_build.utils import package_has_file, FileNotFoundError

thisdir = os.path.dirname(__file__)
recipe_dir = os.path.join(thisdir, 'test-recipes', 'variants')


def test_later_spec_priority(single_version, no_numpy_version):
    # override a single key
    specs = OrderedDict()
    specs['no_numpy'] = no_numpy_version
    specs['single_ver'] = single_version
    combined_spec = variants.combine_specs(specs)
    assert len(combined_spec) == 2
    assert combined_spec["python"] == ["2.7.*"]
    assert combined_spec['extend_keys'] == {'ignore_version', 'pin_run_as_build', 'ignore_build_only_deps', 'extend_keys'}

    # keep keys that are not overwritten
    specs = OrderedDict()
    specs['single_ver'] = single_version
    specs['no_numpy'] = no_numpy_version
    combined_spec = variants.combine_specs(specs)
    assert len(combined_spec) == 2
    assert len(combined_spec["python"]) == 2


def test_get_package_variants_from_file(testing_workdir, testing_config, no_numpy_version):
    with open('variant_example.yaml', 'w') as f:
        yaml.dump(no_numpy_version, f, default_flow_style=False)
    testing_config.variant_config_files = [os.path.join(testing_workdir, 'variant_example.yaml')]
    testing_config.ignore_system_config = True
    metadata = api.render(os.path.join(thisdir, "variant_recipe"),
                            no_download_source=False, config=testing_config)
    # one for each Python version.  Numpy is not strictly pinned and should present only 1 dimension
    assert len(metadata) == 2
    assert sum('python >=2.7,<2.8' in req for (m, _, _) in metadata
               for req in m.meta['requirements']['run']) == 1
    assert sum('python >=3.5,<3.6' in req for (m, _, _) in metadata
               for req in m.meta['requirements']['run']) == 1


def test_use_selectors_in_variants(testing_workdir, testing_config):
    testing_config.variant_config_files = [os.path.join(recipe_dir,
                                                        'selector_conda_build_config.yaml')]
    variants.get_package_variants(testing_workdir, testing_config)


def test_get_package_variants_from_dictionary_of_lists(testing_config, no_numpy_version):
    testing_config.ignore_system_config = True
    metadata = api.render(os.path.join(thisdir, "variant_recipe"),
                          no_download_source=False, config=testing_config,
                          variants=no_numpy_version)
    # one for each Python version.  Numpy is not strictly pinned and should present only 1 dimension
    assert len(metadata) == 2, metadata
    assert sum('python >=2.7,<2.8' in req for (m, _, _) in metadata
               for req in m.meta['requirements']['run']) == 1
    assert sum('python >=3.5,<3.6' in req for (m, _, _) in metadata
               for req in m.meta['requirements']['run']) == 1


@pytest.mark.xfail(reason="Strange failure 7/19/2017.  Can't reproduce locally.  Test runs fine "
                   "with parallelism and everything.  Test fails reproducibly on CI, but logging "
                   "into appveyor after failed run, test passes.  =(")
def test_variant_with_ignore_numpy_version_reduces_matrix(numpy_version_ignored):
    # variants are defined in yaml file in this folder
    # there are two python versions and two numpy versions.  However, because numpy is not pinned,
    #    the numpy dimensions should get collapsed.
    recipe = os.path.join(recipe_dir, '03_numpy_matrix')
    metadata = api.render(recipe, variants=numpy_version_ignored, finalize=False)
    assert len(metadata) == 2, metadata


def test_variant_with_numpy_pinned_has_matrix():
    recipe = os.path.join(recipe_dir, '04_numpy_matrix_pinned')
    metadata = api.render(recipe, finalize=False)
    assert len(metadata) == 4


def test_pinning_in_build_requirements():
    recipe = os.path.join(recipe_dir, '05_compatible')
    metadata = api.render(recipe)[0][0]
    build_requirements = metadata.meta['requirements']['build']
    # make sure that everything in the build deps is exactly pinned
    assert all(len(req.split(' ')) == 3 for req in build_requirements)


def test_no_satisfiable_variants_raises_error():
    recipe = os.path.join(recipe_dir, '01_basic_templating')
    with pytest.raises(exceptions.DependencyNeedsBuildingError):
        api.render(recipe, permit_unsatisfiable_variants=False)

    # the packages are not installable anyway, so this should show a warning that recipe can't
    #   be finalized
    api.render(recipe, permit_unsatisfiable_variants=True)
    # out, err = capsys.readouterr()
    # print(out)
    # print(err)
    # print(caplog.text)
    # assert "Returning non-final recipe; one or more dependencies was unsatisfiable" in err


def test_zip_fields():
    """Zipping keys together allows people to tie different versions as sets of combinations."""
    v = {'python': ['2.7', '3.5'], 'vc': ['9', '14'], 'zip_keys': [('python', 'vc')]}
    ld = variants.dict_of_lists_to_list_of_dicts(v)
    assert len(ld) == 2
    assert ld[0]['python'] == '2.7'
    assert ld[0]['vc'] == '9'
    assert ld[1]['python'] == '3.5'
    assert ld[1]['vc'] == '14'

    # allow duplication of values, but lengths of lists must always match
    v = {'python': ['2.7', '2.7'], 'vc': ['9', '14'], 'zip_keys': [('python', 'vc')]}
    ld = variants.dict_of_lists_to_list_of_dicts(v)
    assert len(ld) == 2
    assert ld[0]['python'] == '2.7'
    assert ld[0]['vc'] == '9'
    assert ld[1]['python'] == '2.7'
    assert ld[1]['vc'] == '14'

    # mismatched lengths should raise an error
    v = {'python': ['2.7', '3.5', '3.4'], 'vc': ['9', '14'], 'zip_keys': [('python', 'vc')]}
    with pytest.raises(ValueError):
        ld = variants.dict_of_lists_to_list_of_dicts(v)

    # WHEN one is completely missing, it's OK.  The zip_field for the set gets ignored.
    v = {'python': ['2.7', '3.5'], 'zip_keys': [('python', 'vc')]}
    ld = variants.dict_of_lists_to_list_of_dicts(v)
    assert len(ld) == 2
    assert 'vc' not in ld[0].keys()
    assert 'vc' not in ld[1].keys()


def test_cross_compilers():
    recipe = os.path.join(recipe_dir, '09_cross')
    ms = api.render(recipe, permit_unsatisfiable_variants=True, finalize=False, bypass_env_check=True)
    assert len(ms) == 3


def test_variants_in_output_names():
    recipe = os.path.join(recipe_dir, '11_variant_output_names')
    outputs = api.get_output_file_paths(recipe)
    assert len(outputs) == 4


def test_variants_in_versions_with_setup_py_data(testing_workdir):
    recipe = os.path.join(recipe_dir, '12_variant_versions')
    try:
        outputs = api.get_output_file_paths(recipe)
        assert len(outputs) == 2
        assert any(os.path.basename(pkg).startswith('my_package-470.470') for pkg in outputs)
        assert any(os.path.basename(pkg).startswith('my_package-480.480') for pkg in outputs)
    except FileNotFoundError:
        # problem with python 3.x with Travis CI somehow.  Just ignore it.
        print("Ignoring test on setup.py data - problem with download")


def test_git_variables_with_variants(testing_workdir, testing_config):
    recipe = os.path.join(recipe_dir, '13_git_vars')
    m = api.render(recipe, config=testing_config, finalize=False, bypass_env_check=True)[0][0]
    assert m.version() == "1.20.2"
    assert m.build_number() == 0


def test_variant_input_with_zip_keys_keeps_zip_keys_list():
    variants_ = {'scipy': ['0.17', '0.19'], 'sqlite': ['3'], 'zlib': ['1.2'], 'xz': ['5'],
                 'zip_keys': ['macos_min_version', 'macos_machine', 'MACOSX_DEPLOYMENT_TARGET',
                              'CONDA_BUILD_SYSROOT'],
                 'pin_run_as_build': {'python': {'min_pin': 'x.x', 'max_pin': 'x.x'}}}
    variant_list = variants.dict_of_lists_to_list_of_dicts(variants_,
                        extend_keys=variants.DEFAULT_VARIANTS['extend_keys'])
    assert len(variant_list) == 2
    assert 'zip_keys' in variant_list[0] and variant_list[0]['zip_keys']


@pytest.mark.xfail(sys.platform=='win32', reason="console readout issues on appveyor")
def test_ensure_valid_spec_on_run_and_test(testing_workdir, testing_config, caplog):
    recipe = os.path.join(recipe_dir, '14_variant_in_run_and_test')
    api.render(recipe, config=testing_config)

    text = caplog.text
    assert "Adding .* to spec 'pytest  3.2'" in text
    assert "Adding .* to spec 'click  6'" in text
    assert "Adding .* to spec 'pytest-cov  2.3'" not in text
    assert "Adding .* to spec 'pytest-mock  1.6'" not in text


def test_serial_builds_have_independent_configs(testing_config):
    recipe = os.path.join(recipe_dir, '17_multiple_recipes_independent_config')
    recipes = [os.path.join(recipe, dirname) for dirname in ('a', 'b')]
    outputs = api.build(recipes, config=testing_config)
    index_json = json.loads(package_has_file(outputs[0], 'info/index.json'))
    assert 'bzip2 >=1,<1.0.7.0a0' in index_json['depends']
    index_json = json.loads(package_has_file(outputs[1], 'info/index.json'))
    assert 'bzip2 >=1.0.6,<2.0a0' in index_json['depends']


def test_subspace_selection(testing_config):
    recipe = os.path.join(recipe_dir, '18_subspace_selection')
    testing_config.variant = {'a': 'coffee'}
    ms = api.render(recipe, config=testing_config, finalize=False, bypass_env_check=True)
    # there are two entries with a==coffee, so we should end up with 2 variants
    assert len(ms) == 2
    # ensure that the zipped keys still agree
    assert sum(m.config.variant['b'] == '123' for m, _, _ in ms) == 1
    assert sum(m.config.variant['b'] == 'abc' for m, _, _ in ms) == 1
    assert sum(m.config.variant['b'] == 'concrete' for m, _, _ in ms) == 0
    assert sum(m.config.variant['c'] == 'mooo' for m, _, _ in ms) == 1
    assert sum(m.config.variant['c'] == 'baaa' for m, _, _ in ms) == 1
    assert sum(m.config.variant['c'] == 'woof' for m, _, _ in ms) == 0

    # test compound selection
    testing_config.variant = {'a': 'coffee', 'b': '123'}
    ms = api.render(recipe, config=testing_config, finalize=False, bypass_env_check=True)
    # there are two entries with a==coffee, but one with both 'coffee' for a, and '123' for b,
    #     so we should end up with 1 variants
    assert len(ms) == 1
    # ensure that the zipped keys still agree
    assert sum(m.config.variant['b'] == '123' for m, _, _ in ms) == 1
    assert sum(m.config.variant['b'] == 'abc' for m, _, _ in ms) == 0
    assert sum(m.config.variant['b'] == 'concrete' for m, _, _ in ms) == 0
    assert sum(m.config.variant['c'] == 'mooo' for m, _, _ in ms) == 1
    assert sum(m.config.variant['c'] == 'baaa' for m, _, _ in ms) == 0
    assert sum(m.config.variant['c'] == 'woof' for m, _, _ in ms) == 0

    # test when configuration leads to no valid combinations - only c provided, and its value
    #   doesn't match any other existing values of c, so it's then ambiguous which zipped
    #   values to choose
    testing_config.variant = {'c': 'not an animal'}
    with pytest.raises(ValueError):
        ms = api.render(recipe, config=testing_config, finalize=False, bypass_env_check=True)

    # all zipped keys provided by the new variant.  It should clobber the old one.
    testing_config.variant = {'a': 'some', 'b': 'new', 'c': 'animal'}
    ms = api.render(recipe, config=testing_config, finalize=False, bypass_env_check=True)
    assert len(ms) == 1
    assert ms[0][0].config.variant['a'] == 'some'
    assert ms[0][0].config.variant['b'] == 'new'
    assert ms[0][0].config.variant['c'] == 'animal'


def test_get_used_loop_vars(testing_config):
    m = api.render(os.path.join(recipe_dir, '19_used_variables'), finalize=False, bypass_env_check=True)[0][0]
    # conda_build_config.yaml has 4 loop variables defined, but only 3 are used.
    #   python and zlib are both implicitly used (depend on name matching), while
    #   some_package is explicitly used as a jinja2 variable
    assert m.get_used_loop_vars() == {'python', 'some_package'}
    # these are all used vars - including those with only one value (and thus not loop vars)
    assert m.get_used_vars() == {'python', 'some_package', 'zlib', 'pthread_stubs'}


def test_reprovisioning_source(testing_config):
    ms = api.render(os.path.join(recipe_dir, '20_reprovision_source'))


def test_reduced_hashing_behavior(testing_config):
    # recipes using any compiler jinja2 function need a hash
    m = api.render(os.path.join(recipe_dir, '26_reduced_hashing', 'hash_yes_compiler'),
                   finalize=False, bypass_env_check=True)[0][0]
    assert 'c_compiler' in m.get_hash_contents(), "hash contents should contain c_compiler"
    assert re.search('h[0-9a-f]{%d}' % testing_config.hash_length, m.build_id()), \
        "hash should be present when compiler jinja2 function is used"

    # recipes that use some variable in conda_build_config.yaml to control what
    #     versions are present at build time also must have a hash (except
    #     python, r_base, and the other stuff covered by legacy build string
    #     behavior)
    m = api.render(os.path.join(recipe_dir, '26_reduced_hashing', 'hash_yes_pinned'),
                   finalize=False, bypass_env_check=True)[0][0]
    assert 'zlib' in m.get_hash_contents()
    assert re.search('h[0-9a-f]{%d}' % testing_config.hash_length, m.build_id())

    # anything else does not get a hash
    m = api.render(os.path.join(recipe_dir, '26_reduced_hashing', 'hash_no_python'),
                   finalize=False, bypass_env_check=True)[0][0]
    assert not m.get_hash_contents()
    assert not re.search('h[0-9a-f]{%d}' % testing_config.hash_length, m.build_id())


def test_variants_used_in_jinja2_conditionals(testing_config):
    ms = api.render(os.path.join(recipe_dir, '21_conditional_sections'),
                    finalize=False, bypass_env_check=True)
    assert len(ms) == 2
    assert sum(m.config.variant['blas_impl'] == 'mkl' for m, _, _ in ms) == 1
    assert sum(m.config.variant['blas_impl'] == 'openblas' for m, _, _ in ms) == 1


def test_build_run_exports_act_on_host(testing_config, caplog):
    """Regression test for https://github.com/conda/conda-build/issues/2559"""
    api.render(os.path.join(recipe_dir, '22_run_exports_rerendered_for_other_variants'),
                    platform='win', arch='64')
    assert "failed to get install actions, retrying" not in caplog.text


def test_detect_variables_in_build_and_output_scripts(testing_config):
    ms = api.render(os.path.join(recipe_dir, '24_test_used_vars_in_scripts'),
                    platform='linux', arch='64')
    for m, _, _ in ms:
        if m.name() == 'test_find_used_variables_in_scripts':
            used_vars = m.get_used_vars()
            assert used_vars
            assert 'SELECTOR_VAR' in used_vars
            assert 'OUTPUT_SELECTOR_VAR' not in used_vars
            assert 'BASH_VAR1' in used_vars
            assert 'BASH_VAR2' in used_vars
            assert 'BAT_VAR' not in used_vars
            assert 'OUTPUT_VAR' not in used_vars
        else:
            used_vars = m.get_used_vars()
            assert used_vars
            assert 'SELECTOR_VAR' not in used_vars
            assert 'OUTPUT_SELECTOR_VAR' in used_vars
            assert 'BASH_VAR1' not in used_vars
            assert 'BASH_VAR2' not in used_vars
            assert 'BAT_VAR' not in used_vars
            assert 'OUTPUT_VAR' in used_vars
    # on windows, we find variables in bat scripts as well as shell scripts
    ms = api.render(os.path.join(recipe_dir, '24_test_used_vars_in_scripts'),
                    platform='win', arch='64')
    for m, _, _ in ms:
        if m.name() == 'test_find_used_variables_in_scripts':
            used_vars = m.get_used_vars()
            assert used_vars
            assert 'SELECTOR_VAR' in used_vars
            assert 'OUTPUT_SELECTOR_VAR' not in used_vars
            assert 'BASH_VAR1' in used_vars
            assert 'BASH_VAR2' in used_vars
            # bat is in addition to bash, not instead of
            assert 'BAT_VAR' in used_vars
            assert 'OUTPUT_VAR' not in used_vars
        else:
            used_vars = m.get_used_vars()
            assert used_vars
            assert 'SELECTOR_VAR' not in used_vars
            assert 'OUTPUT_SELECTOR_VAR' in used_vars
            assert 'BASH_VAR1' not in used_vars
            assert 'BASH_VAR2' not in used_vars
            assert 'BAT_VAR' not in used_vars
            assert 'OUTPUT_VAR' in used_vars


def test_target_platform_looping(testing_config):
    outputs = api.get_output_file_paths(os.path.join(recipe_dir, '25_target_platform_looping'),
                                   platform='win', arch='64')
    assert len(outputs) == 2


@pytest.mark.serial
def test_numpy_used_variable_looping(testing_config):
    outputs = api.get_output_file_paths(os.path.join(recipe_dir, 'numpy_used'))
    assert len(outputs) == 4


def test_exclusive_config_files(testing_workdir):
    with open('conda_build_config.yaml', 'w') as f:
        yaml.dump({'abc': ['someval'], 'cwd': ['someval']}, f, default_flow_style=False)
    os.makedirs('config_dir')
    with open(os.path.join('config_dir', 'config-0.yaml'), 'w') as f:
        yaml.dump({'abc': ['super_0'], 'exclusive_0': ['0'], 'exclusive_both': ['0']},
                  f, default_flow_style=False)
    with open(os.path.join('config_dir', 'config-1.yaml'), 'w') as f:
        yaml.dump({'abc': ['super_1'], 'exclusive_1': ['1'], 'exclusive_both': ['1']},
                  f, default_flow_style=False)
    exclusive_config_files = (
        os.path.join('config_dir', 'config-0.yaml'),
        os.path.join('config_dir', 'config-1.yaml'),
    )
    output = api.render(os.path.join(recipe_dir, 'exclusive_config_file'),
                        exclusive_config_files=exclusive_config_files)[0][0]
    variant = output.config.variant
    # is cwd ignored?
    assert 'cwd' not in variant
    # did we load the exclusive configs?
    assert variant['exclusive_0'] == '0'
    assert variant['exclusive_1'] == '1'
    # does later exclusive config override initial one?
    assert variant['exclusive_both'] == '1'
    # does recipe config override exclusive?
    assert 'unique_to_recipe' in variant
    assert variant['abc'] == '123'


def test_exclusive_config_file(testing_workdir):
    with open('conda_build_config.yaml', 'w') as f:
        yaml.dump({'abc': ['someval'], 'cwd': ['someval']}, f, default_flow_style=False)
    os.makedirs('config_dir')
    with open(os.path.join('config_dir', 'config.yaml'), 'w') as f:
        yaml.dump({'abc': ['super'], 'exclusive': ['someval']}, f, default_flow_style=False)
    output = api.render(os.path.join(recipe_dir, 'exclusive_config_file'),
                        exclusive_config_file=os.path.join('config_dir', 'config.yaml'))[0][0]
    variant = output.config.variant
    # is cwd ignored?
    assert 'cwd' not in variant
    # did we load the exclusive config
    assert 'exclusive' in variant
    # does recipe config override exclusive?
    assert 'unique_to_recipe' in variant
    assert variant['abc'] == '123'


@pytest.mark.serial
def test_inner_python_loop_with_output(testing_config):
    outputs = api.get_output_file_paths(os.path.join(recipe_dir, 'test_python_as_subpackage_loop'),
                                        config=testing_config)
    outputs = [os.path.basename(out) for out in outputs]
    assert len(outputs) == 5
    assert len([out for out in outputs if out.startswith('tbb-2018')]) == 1
    assert len([out for out in outputs if out.startswith('tbb-devel-2018')]) == 1
    assert len([out for out in outputs if out.startswith('tbb4py-2018')]) == 3

    testing_config.variant_config_files = [os.path.join(recipe_dir, 'test_python_as_subpackage_loop', 'config_with_zip.yaml')]
    outputs = api.get_output_file_paths(os.path.join(recipe_dir, 'test_python_as_subpackage_loop'),
                                        config=testing_config)
    outputs = [os.path.basename(out) for out in outputs]
    assert len(outputs) == 5
    assert len([out for out in outputs if out.startswith('tbb-2018')]) == 1
    assert len([out for out in outputs if out.startswith('tbb-devel-2018')]) == 1
    assert len([out for out in outputs if out.startswith('tbb4py-2018')]) == 3

    testing_config.variant_config_files = [os.path.join(recipe_dir, 'test_python_as_subpackage_loop', 'config_with_zip.yaml')]
    outputs = api.get_output_file_paths(os.path.join(recipe_dir, 'test_python_as_subpackage_loop'),
                                        config=testing_config, platform='win', arch=64)
    outputs = [os.path.basename(out) for out in outputs]
    assert len(outputs) == 5
    assert len([out for out in outputs if out.startswith('tbb-2018')]) == 1
    assert len([out for out in outputs if out.startswith('tbb-devel-2018')]) == 1
    assert len([out for out in outputs if out.startswith('tbb4py-2018')]) == 3


def test_variant_as_dependency_name(testing_config):
    outputs = api.render(os.path.join(recipe_dir, '27_requirements_host'),
                                        config=testing_config)
    assert len(outputs) == 2


def test_custom_compiler():
    recipe = os.path.join(recipe_dir, '28_custom_compiler')
    ms = api.render(recipe, permit_unsatisfiable_variants=True, finalize=False, bypass_env_check=True)
    assert len(ms) == 3


def test_different_git_vars():
    recipe = os.path.join(recipe_dir, '29_different_git_vars')
    ms = api.render(recipe)
    versions = [m[0].version() for m in ms]
    assert "1.20.0" in versions
    assert "1.21.11" in versions
