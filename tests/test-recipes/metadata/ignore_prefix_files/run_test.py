from glob import glob
import os
import subprocess

print("$$$$$$ROOT$$$$$$$ = ")
print(os.environ["ROOT"])
print("^^^^^ENVIRON^^^^^^")
print(os.environ)
pkgs = os.path.abspath(os.path.join(os.environ["ROOT"], "pkgs"))
subprocess.run(['cd', pkgs])
subprocess.check_output(['ls', '-l'])
for path in glob(os.path.join(pkgs, "conda-build-test-ignore-prefix-files-1.0-0")):
    print("--------")
    print(path)
pkg_dir = glob(os.path.join(pkgs, "conda-build-test-ignore-prefix-files-1.0-0"))[0]
info_dir = os.path.join(pkg_dir, 'info')
assert os.path.isdir(info_dir)
assert not os.path.isfile(os.path.join(info_dir, "has_prefix"))
