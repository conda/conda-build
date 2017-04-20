import os

import pytest
import yaml

from conda_build import api, exceptions, variants

global_specs = {"python": ["2.7.*", "3.5.*"],
                "numpy": ["1.10.*", "1.11.*"]}

single_version = {"python": "2.7.*",
                  "numpy": "1.11.*"}

no_numpy_version = {"python": ["2.7.*", "3.5.*"]}

thisdir = os.path.dirname(__file__)
recipe_dir = os.path.join(thisdir, 'test-recipes', 'variants')


def test_later_spec_priority():
    # override a single key
    combined_spec, extend_keys = variants.combine_specs([global_specs, single_version])
    assert len(combined_spec) == 2
    assert combined_spec["python"] == ["2.7.*"]
    assert extend_keys == {'ignore_version', 'pin_run_as_build'}

    # keep keys that are not overwritten
    combined_spec, extend_keys = variants.combine_specs([single_version, no_numpy_version])
    assert len(combined_spec) == 2
    assert len(combined_spec["python"]) == 2


def test_get_package_variants_from_file(testing_workdir, testing_config):
    variants = global_specs.copy()
    variants['ignore_version'] = ['numpy']
    with open('variant_example.yaml', 'w') as f:
        yaml.dump(variants, f, default_flow_style=False)
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


def test_get_package_variants_from_dictionary_of_lists(testing_config):
    testing_config.ignore_system_config = True
    variants = global_specs.copy()
    variants['ignore_version'] = ['numpy']
    # Note: variant is coming from up above: global_specs
    metadata = api.render(os.path.join(thisdir, "variant_recipe"),
                          no_download_source=False, config=testing_config,
                          variants=variants)
    # one for each Python version.  Numpy is not strictly pinned and should present only 1 dimension
    assert len(metadata) == 2
    assert sum('python >=2.7,<2.8' in req for (m, _, _) in metadata
               for req in m.meta['requirements']['run']) == 1
    assert sum('python >=3.5,<3.6' in req for (m, _, _) in metadata
               for req in m.meta['requirements']['run']) == 1


def test_combine_variants():
    v1 = {'python': '2.7.*', 'extend_keys': ['dict', 'list'], 'list': 'steve',
          'dict': {'some': 'value'}}
    v2 = {'python': '3.5.*', 'list': 'frank', 'dict': {'some': 'other', 'test': 'value'}}
    combined = variants.combine_variants(v1, v2)
    assert combined['python'] == '3.5.*'
    assert set(combined['list']) == {'steve', 'frank'}
    assert len(combined['dict']) == 2
    assert combined['dict']['some'] == 'other'


def test_variant_with_numpy_not_pinned_reduces_matrix():
    # variants are defined in yaml file in this folder
    # there are two python versions and two numpy versions.  However, because numpy is not pinned,
    #    the numpy dimensions should get collapsed.
    recipe = os.path.join(recipe_dir, '03_numpy_matrix')
    metadata = api.render(recipe)
    assert len(metadata) == 2


def test_pinning_in_build_requirements():
    recipe = os.path.join(recipe_dir, '05_compatible')
    metadata = api.render(recipe)[0][0]
    build_requirements = metadata.meta['requirements']['build']
    # make sure that everything in the build deps is exactly pinned
    assert all(len(req.split(' ')) == 3 for req in build_requirements)


def test_no_satisfiable_variants_raises_error(caplog):
    recipe = os.path.join(recipe_dir, '01_basic_templating')
    with pytest.raises(exceptions.DependencyNeedsBuildingError):
        api.render(recipe, permit_unsatisfiable_variants=False)

    # the packages are not installable anyway, so this should show a warning that recipe can't
    #   be finalized
    api.render(recipe, permit_unsatisfiable_variants=True)
    assert "Could not finalize metadata due to missing dependencies" in caplog.text


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

    # when one is completely missing, it's OK.  The zip_field for the set gets ignored.
    v = {'python': ['2.7', '3.5'], 'zip_keys': [('python', 'vc')]}
    ld = variants.dict_of_lists_to_list_of_dicts(v)
    assert len(ld) == 2
    assert 'vc' not in ld[0].keys()
    assert 'vc' not in ld[1].keys()


def test_cross_compilers():
    recipe = os.path.join(recipe_dir, '09_cross')
    outputs = api.get_output_file_paths(recipe)
    assert len(outputs) == 3
