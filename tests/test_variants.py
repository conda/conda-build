import os

from conda_build import variants
from conda_build import api

import yaml

global_specs = {"python": ["2.7.*", "3.5.*"],
                "numpy": ["1.10.*", "1.11.*"]}

single_version = {"python": "2.7.*",
                  "numpy": "1.11.*"}

no_numpy_version = {"python": ["2.7.*", "3.5.*"]}

thisdir = os.path.dirname(__file__)


def test_later_spec_priority():
    # override a single key
    combined_spec, extend_keys = variants.combine_specs([global_specs, single_version])
    assert len(combined_spec) == 2
    assert combined_spec["python"] == ["2.7.*"]
    assert extend_keys == set(['pin_run_as_build'])

    # keep keys that are not overwritten
    combined_spec, extend_keys = variants.combine_specs([single_version, no_numpy_version])
    assert len(combined_spec) == 2
    assert len(combined_spec["python"]) == 2


def test_get_package_variants_from_file(testing_workdir, testing_config):
    with open('variant_example.yaml', 'w') as f:
        yaml.dump(global_specs, f)
    testing_config.variant_config_files = [os.path.join(testing_workdir, 'variant_example.yaml')]
    testing_config.ignore_system_config = True
    metadata = api.render(os.path.join(thisdir, "variant_recipe"),
                            no_download_source=False, config=testing_config)
    # one for each Python version.  Numpy is not strictly pinned and should present only 1 dimension
    assert len(metadata) == 2
    assert sum('python 2.7' in req for (m, _, _) in metadata
               for req in m.meta['requirements']['run']) == 1
    assert sum('python 3.5' in req for (m, _, _) in metadata
               for req in m.meta['requirements']['run']) == 1


def test_get_package_variants_from_dictionary_of_lists(testing_config):
    testing_config.ignore_system_config = True
    metadata = api.render(os.path.join(thisdir, "variant_recipe"),
                          no_download_source=False, config=testing_config,
                          variants=global_specs)
    # one for each Python version.  Numpy is not strictly pinned and should present only 1 dimension
    assert len(metadata) == 2
    assert sum('python 2.7' in req for (m, _, _) in metadata
               for req in m.meta['requirements']['run']) == 1
    assert sum('python 3.5' in req for (m, _, _) in metadata
               for req in m.meta['requirements']['run']) == 1


def test_combine_variants():
    v1 = {'python': '2.7.*', 'extend_keys': 'frank', 'frank': 'steve'}
    v2 = {'python': '3.5.*', 'extend_keys': 'frank', 'frank': 'bruce'}
    combined = variants.combine_variants(v1, v2)
    assert combined['python'] == '3.5.*'
    assert combined['frank'] == set(['steve', 'bruce'])
