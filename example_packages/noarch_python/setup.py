from distutils.core import setup

setup(
    name = "foo",
    version = '1.2.3',
    author = "Ilan Schnell",
    py_modules = ["foo"],
    entry_points = {
        'console_scripts': ['foo = foo:main'],
    },
)
