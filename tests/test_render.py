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
    reqs = {'build': ['exact', 'exact 1.2.3 1', 'exact >1.0,<2',
                      'bounded >=1.0,<2.0', 'bounded >=1.5', 'bounded <=1.8'],
            'host': ['exact', 'exact 1.2.3 1', 'bounded >=1.0,<2.0', 'bounded >=1.5', 'bounded <=1.8'],
            'run': ['exact', 'exact 1.2.3 1', 'bounded >=1.0,<2.0', 'bounded >=1.5', 'bounded <=1.8'],
    }
    testing_metadata.meta['requirements'] = reqs
    render._simplify_to_tightest_constraint(testing_metadata)
    assert (testing_metadata.meta['requirements']['build'] ==
            testing_metadata.meta['requirements']['host'] ==
            testing_metadata.meta['requirements']['run'])
    simplified_deps = testing_metadata.meta['requirements']
    assert len(simplified_deps['build']) == 2
    assert 'exact 1.2.3 1' in simplified_deps['build']
    # currently we lose the >= in the upper bound.  I don't think that's going to be a huge issue,
    #     but we'll see.  I don't really want to track the bound - just the bound type (upper/lower)
    assert 'bounded >=1.5,<1.8' in simplified_deps['build']
