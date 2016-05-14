# import setuptools
from distutils.core import setup

#setuptools  # fool pyflakes

name = 'noarch_test_package'

setup(
    name=name,
    version='1.0',
    author='Almar',
    author_email='almar@notmyemail.com',
    url='http://continuum.io',
    license='(new) BSD',
    description='testing noarch package building',
    platforms='any',
    provides=[name],
    py_modules=[name],
    entry_points={'console_scripts': ['%s_script = %s:main' % (name, name)], },
)
