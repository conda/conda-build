import os
import subprocess

import noarch_python_test_package

pkgs_dir = os.path.abspath(os.path.join(os.environ["ROOT"], 'pkgs'))
pkg_dir = os.path.join(pkgs_dir, 'noarch_python_test_package-1.0-py_0')

assert os.path.isdir(pkg_dir)

site_packages = os.path.join(pkg_dir, 'site-packages')
assert os.path.isdir(site_packages)

# Check module

assert noarch_python_test_package.answer == 142

# Check entry point

res = subprocess.check_output(['noarch_python_test_package_script']).decode('utf-8').strip()
assert res == '242'
