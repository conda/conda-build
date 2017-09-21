import os
import subprocess

import noarch_test_package

pkgs_dir = os.path.abspath(os.path.join(os.environ["ROOT"], 'pkgs'))
package_dir_name = 'noarch_test_package-1.0-py_0'
pkg_dir = os.path.join(pkgs_dir, package_dir_name)

if not os.path.isdir(pkg_dir):
    channel_name = os.path.basename(os.path.dirname(os.path.dirname(os.environ["PREFIX"])))
    print("channel_name: %s" % channel_name)
    pkg_dir = os.path.join(pkgs_dir, channel_name, 'noarch', package_dir_name)
    print(pkg_dir)
    if not os.path.isdir(pkg_dir):
        raise RuntimeError("No pkg_dir found: %s" % pkg_dir)

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
