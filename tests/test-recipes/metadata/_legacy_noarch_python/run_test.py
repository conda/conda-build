from glob import glob
import os
import subprocess

import noarch_test_package

pkgs_dir = os.path.abspath(os.path.join(os.environ["ROOT"], 'pkgs'))
pkg_dir = glob(os.path.join(pkgs_dir, 'noarch_test_package-1.0-pyh*_0'))[0]

assert os.path.isdir(pkg_dir)

# Check newlines in prelink scripts
# The one for the .sh is crucial, the one for the .bat is just good behavior

fname_prelink_unix = os.path.join(pkg_dir, 'bin', '.noarch_test_package-pre-link.sh')
fname_prelink_win = os.path.join(pkg_dir, 'Scripts', '.noarch_test_package-pre-link.bat')

prelink_unix = open(fname_prelink_unix, 'rb').read().decode('utf-8')
prelink_win = open(fname_prelink_win, 'rb').read().decode('utf-8')

assert prelink_unix.count('\n') and not prelink_unix.count('\r')
assert prelink_win.count('\n') == prelink_win.count('\r')

# Check module

assert noarch_test_package.answer == 142

# Check entry point

res = subprocess.check_output(['noarch_test_package_script']).decode('utf-8').strip()
assert res == '242'
