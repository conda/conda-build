from conda_build.skeletons import pypi


def test_version_compare():
    short_version = '2.2'
    long_version = '1.4.5'
    post_version = '2.2.post3'
    pre_version = '2.2.pre3'
    alpha_version = '1.4.5a4'
    beta_version = '1.4.5b4'
    rc_version = '1.4.5rc4'
    padding_version_short = '2.2.0'
    padding_version_long = '1.4.5.0'

    assert pypi.convert_version(short_version) == ' >=2.2,<3'
    assert pypi.convert_version(long_version) == ' >=1.4.5,<1.5'
    assert pypi.convert_version(post_version) == ' >=2.2.post3,<3'
    assert pypi.convert_version(pre_version) == ' >=2.2.pre3,<3'
    assert pypi.convert_version(alpha_version) == ' >=1.4.5a4,<1.5'
    assert pypi.convert_version(beta_version) == ' >=1.4.5b4,<1.5'
    assert pypi.convert_version(rc_version) == ' >=1.4.5rc4,<1.5'
    assert pypi.convert_version(padding_version_short) == ' >=2.2.0,<2.3'
    assert pypi.convert_version(padding_version_long) == ' >=1.4.5.0,<1.4.6'
