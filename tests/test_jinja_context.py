from conda_build import jinja_context


def test_pin_default(testing_config, mocker):
    get_installed_packages = mocker.patch.object(jinja_context, 'get_installed_packages')
    get_installed_packages.return_value = {'test': {'version': '1.2.3'}}
    testing_config.variant = {'compatible': {'test': 'p.p'}}
    pin = jinja_context.pin_compatible(testing_config, 'test')
    assert pin == '>=1.2.3,<1.3'


def test_pin_jpeg_style_default(testing_config, mocker):
    get_installed_packages = mocker.patch.object(jinja_context, 'get_installed_packages')
    get_installed_packages.return_value = {'jpeg': {'version': '9d'}}
    pin = jinja_context.pin_compatible(testing_config, 'jpeg')
    assert pin == '>=9d,<10'


def test_pin_jpeg_style_minor(testing_config, mocker):
    get_installed_packages = mocker.patch.object(jinja_context, 'get_installed_packages')
    get_installed_packages.return_value = {'jpeg': {'version': '9d'}}
    testing_config.variant = {'compatible': {'jpeg': 'p.p'}}
    pin = jinja_context.pin_compatible(testing_config, 'jpeg')
    assert pin == '>=9d,<9e'


def test_pin_major_minor(testing_config, mocker):
    get_installed_packages = mocker.patch.object(jinja_context, 'get_installed_packages')
    get_installed_packages.return_value = {'test': {'version': '1.2.3'}}
    testing_config.variant = {'compatible': {'test': 'p.p'}}
    pin = jinja_context.pin_compatible(testing_config, 'test')
    assert pin == '>=1.2.3,<1.3'
