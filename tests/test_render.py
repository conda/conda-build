import os
from conda_build import api


def test_output_with_noarch_says_noarch(testing_metadata):
    testing_metadata.meta['build']['noarch'] = 'python'
    output = api.get_output_file_path(testing_metadata)
    assert os.path.sep + "noarch" + os.path.sep in output[0]


def test_output_with_noarch_python_says_noarch(testing_metadata):
    testing_metadata.meta['build']['noarch_python'] = True
    output = api.get_output_file_path(testing_metadata)
    assert os.path.sep + "noarch" + os.path.sep in output[0]


# no tests here - this is tested at a high level in test_cli.py and in test_api_render.py.
#   tests here should be lower-level unit tests of the render.py functionality.
