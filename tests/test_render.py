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


def test_insert_variant_versions(testing_metadata):
    testing_metadata.meta['requirements']['build'] = ['python', 'numpy 1.13']
    testing_metadata.config.variant = {'python': '2.7', 'numpy': '1.11'}
    render.insert_variant_versions(testing_metadata, 'build')
    # this one gets inserted
    assert 'python 2.7' in testing_metadata.meta['requirements']['build']
    # this one should not be altered
    assert 'numpy 1.13' in testing_metadata.meta['requirements']['build']
    # the overall length does not change
    assert len(testing_metadata.meta['requirements']['build']) == 2
