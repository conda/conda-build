import pytest

from conda_build import jinja_context
from conda_build.utils import HashableDict


def test_pin_default(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['test 1.2.3'], []
    pin = jinja_context.pin_compatible(testing_metadata, 'test')
    assert pin == '>=1.2.3,<2'

def test_pin_compatible_exact(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['test 1.2.3 abc_0'], []
    pin = jinja_context.pin_compatible(testing_metadata, 'test', exact=True)
    assert pin == '1.2.3 abc_0'

def test_pin_jpeg_style_default(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['jpeg 9d 0'], []
    pin = jinja_context.pin_compatible(testing_metadata, 'jpeg')
    assert pin == '>=9d,<10'


def test_pin_jpeg_style_minor(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['jpeg 9d 0'], []
    pin = jinja_context.pin_compatible(testing_metadata, 'jpeg', max_pin='x.x')
    assert pin == '>=9d,<9e'


def test_pin_openssl_style_bugfix(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['openssl 1.0.2j 0'], []
    pin = jinja_context.pin_compatible(testing_metadata, 'openssl', max_pin='x.x.x')
    assert pin == '>=1.0.2j,<1.0.3'
    pin = jinja_context.pin_compatible(testing_metadata, 'openssl', max_pin='x.x.x.x')
    assert pin == '>=1.0.2j,<1.0.2k'


def test_pin_major_minor(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['test 1.2.3'], []
    pin = jinja_context.pin_compatible(testing_metadata, 'test', max_pin='x.x')
    assert pin == '>=1.2.3,<1.3'


def test_pin_upper_bound(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['test 1.2.3'], []
    pin = jinja_context.pin_compatible(testing_metadata, 'test', upper_bound="3.0")
    assert pin == '>=1.2.3,<3.0'


def test_pin_lower_bound(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['test 1.2.3'], []
    pin = jinja_context.pin_compatible(testing_metadata, 'test', lower_bound=1.0, upper_bound="3.0")
    assert pin == '>=1.0,<3.0'


def test_pin_none_min(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['test 1.2.3'], []
    pin = jinja_context.pin_compatible(testing_metadata, 'test', min_pin=None)
    assert pin == '<2'


def test_pin_none_max(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['test 1.2.3'], []
    pin = jinja_context.pin_compatible(testing_metadata, 'test', max_pin=None)
    assert pin == '>=1.2.3'


def test_pin_subpackage_exact(testing_metadata):
    output_dict = {'name': 'a'}
    testing_metadata.meta['outputs'] = [output_dict]
    fm = testing_metadata.get_output_metadata(output_dict)
    testing_metadata.other_outputs = {('a', HashableDict(testing_metadata.config.variant)):
                                      (output_dict, fm)}
    pin = jinja_context.pin_subpackage(testing_metadata, 'a', exact=True)
    assert len(pin.split()) == 3


def test_pin_subpackage_expression(testing_metadata):
    output_dict = {'name': 'a'}
    testing_metadata.meta['outputs'] = [output_dict]
    fm = testing_metadata.get_output_metadata(output_dict)
    testing_metadata.other_outputs = {('a', HashableDict(testing_metadata.config.variant)):
                                      (output_dict, fm)}
    pin = jinja_context.pin_subpackage(testing_metadata, 'a')
    assert len(pin.split()) == 2


try:
    from setuptools.config import read_configuration
    del read_configuration
except ImportError:
    _has_read_configuration = False
else:
    _has_read_configuration = True


@pytest.mark.skipif(not _has_read_configuration,
                    reason="setuptools <30.3.0 cannot read metadata / options from 'setup.cfg'")
def test_load_setup_py_data_from_setup_cfg(testing_config, tmpdir):
    setup_py = tmpdir.join('setup.py')
    setup_cfg = tmpdir.join('setup.cfg')
    setup_py.write(
        'from setuptools import setup\n'
        'setup(name="name_from_setup_py")\n'
    )
    setup_cfg.write(
        '[metadata]\n'
        'name = name_from_setup_cfg\n'
        'version = version_from_setup_cfg\n'
        '[options.extras_require]\n'
        'extra = extra_package\n'
    )
    setup_file = str(setup_py)
    setuptools_data = jinja_context.load_setup_py_data(testing_config, setup_file)
    assert setuptools_data['name'] == 'name_from_setup_py'
    assert setuptools_data['version'] == 'version_from_setup_cfg'
    assert setuptools_data['extras_require'] == {'extra': ['extra_package']}
