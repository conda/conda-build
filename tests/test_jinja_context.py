from conda_build import jinja_context


def test_pin_default(testing_config, mocker):
    get_installed_packages = mocker.patch.object(jinja_context, 'get_installed_packages')
    get_installed_packages.return_value = {'test': {'version': '1.2.3'}}
    pin = jinja_context.pin_compatible(testing_config, 'test')
    assert pin == '>=1.2.3,<2'


def test_pin_jpeg_style_default(testing_config, mocker):
    get_installed_packages = mocker.patch.object(jinja_context, 'get_installed_packages')
    get_installed_packages.return_value = {'jpeg': {'version': '9d'}}
    pin = jinja_context.pin_compatible(testing_config, 'jpeg')
    assert pin == '>=9d,<10'


def test_pin_jpeg_style_minor(testing_config, mocker):
    get_installed_packages = mocker.patch.object(jinja_context, 'get_installed_packages')
    get_installed_packages.return_value = {'jpeg': {'version': '9d'}}
    pin = jinja_context.pin_compatible(testing_config, 'jpeg', pins='p.p')
    assert pin == '>=9d,<9e'


def test_pin_major_minor(testing_config, mocker):
    get_installed_packages = mocker.patch.object(jinja_context, 'get_installed_packages')
    get_installed_packages.return_value = {'test': {'version': '1.2.3'}}
    pin = jinja_context.pin_compatible(testing_config, 'test', pins='p.p')
    assert pin == '>=1.2.3,<1.3'


def test_pin_upper_bound(testing_config, mocker):
    get_installed_packages = mocker.patch.object(jinja_context, 'get_installed_packages')
    get_installed_packages.return_value = {'test': {'version': '1.2.3'}}
    pin = jinja_context.pin_compatible(testing_config, 'test', upper_bound="3.0")
    assert pin == '>=1.2.3,<3.0'
