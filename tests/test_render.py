import os
from conda_build import api
from conda_build import render


def test_output_with_noarch_says_noarch(testing_metadata):
    testing_metadata.meta['build']['noarch'] = 'python'
    output = api.get_output_file_path(testing_metadata)
    assert os.path.sep + "noarch" + os.path.sep in output[0]


def test_output_with_noarch_python_says_noarch(testing_metadata):
    testing_metadata.meta['build']['noarch_python'] = True
    output = api.get_output_file_path(testing_metadata)
    assert os.path.sep + "noarch" + os.path.sep in output[0]


def test_reduce_duplicate_specs(testing_metadata):
    reqs = {'build': ['exact', 'exact 1.2.3 1', 'exact >1.0,<2'],
            'host': ['exact', 'exact 1.2.3 1']
    }
    testing_metadata.meta['requirements'] = reqs
    render._simplify_to_exact_constraints(testing_metadata)
    assert (testing_metadata.meta['requirements']['build'] ==
            testing_metadata.meta['requirements']['host'])
    simplified_deps = testing_metadata.meta['requirements']
    assert len(simplified_deps['build']) == 1
    assert 'exact 1.2.3 1' in simplified_deps['build']


def test_pin_run_as_build_preserve_string(testing_metadata):
    m = testing_metadata
    m.config.variant['pin_run_as_build']['pkg'] = {
        'max_pin': 'x.x'
    }
    dep = render.get_pin_from_build(
        m,
        'pkg * somestring*',
        {'pkg': '1.2.3 somestring_h1234'}
    )
    assert dep == 'pkg >=1.2.3,<1.3.0a0 somestring*'
