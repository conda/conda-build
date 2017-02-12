from conda_build import jinja_context


def test_pin_default(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['test 1.2.3']
    pin = jinja_context.pin_compatible(testing_metadata, 'test')
    assert pin == '>=1.2.3,<2'


def test_pin_jpeg_style_default(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['jpeg 9d 0']
    pin = jinja_context.pin_compatible(testing_metadata, 'jpeg')
    assert pin == '>=9d,<10'


def test_pin_jpeg_style_minor(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['jpeg 9d 0']
    pin = jinja_context.pin_compatible(testing_metadata, 'jpeg', pins='p.p')
    assert pin == '>=9d,<9e'


def test_pin_openssl_style_bugfix(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['openssl 1.0.2j 0']
    pin = jinja_context.pin_compatible(testing_metadata, 'openssl', pins='p.p.p')
    assert pin == '>=1.0.2j,<1.0.3'
    pin = jinja_context.pin_compatible(testing_metadata, 'openssl', pins='p.p.p.p')
    assert pin == '>=1.0.2j,<1.0.2k'


def test_pin_major_minor(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['test 1.2.3']
    pin = jinja_context.pin_compatible(testing_metadata, 'test', pins='p.p')
    assert pin == '>=1.2.3,<1.3'


def test_pin_upper_bound(testing_metadata, mocker):
    get_env_dependencies = mocker.patch.object(jinja_context, 'get_env_dependencies')
    get_env_dependencies.return_value = ['test 1.2.3']
    pin = jinja_context.pin_compatible(testing_metadata, 'test', upper_bound="3.0")
    assert pin == '>=1.2.3,<3.0'
