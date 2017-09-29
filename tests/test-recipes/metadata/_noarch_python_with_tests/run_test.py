import os
import subprocess

import noarch_python_test_package

pkgs_dir = os.path.abspath(os.path.join(os.environ["ROOT"], 'pkgs'))
package_dir_name = 'noarch_python_test_package-1.0-py_0'
pkg_dir = os.path.join(pkgs_dir, package_dir_name)

if not os.path.isdir(pkg_dir):
    channel_name = os.path.basename(os.path.dirname(os.path.dirname(os.environ["PREFIX"])))
    print("channel_name: %s" % channel_name)
    pkg_dir = os.path.join(pkgs_dir, channel_name, 'noarch', package_dir_name)
    print(pkg_dir)
    if not os.path.isdir(pkg_dir):
        raise RuntimeError("No pkg_dir found: %s" % pkg_dir)

assert os.path.isdir(pkg_dir)

site_packages = os.path.join(pkg_dir, 'site-packages')
assert os.path.isdir(site_packages)

# Check module

assert noarch_python_test_package.answer == 142

# Check entry point

res = subprocess.check_output(['noarch_python_test_package_script']).decode('utf-8').strip()
assert res == '242'
