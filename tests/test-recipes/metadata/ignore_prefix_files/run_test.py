from glob import glob
import os

pkgs = os.path.join(os.environ["ROOT"], "pkgs")
pkg_dir = glob(os.path.join(pkgs, "conda-build-test-ignore-prefix-files-1.0-h*_0"))[0]
info_dir = os.path.join(pkg_dir, 'info')
assert os.path.isdir(info_dir)
assert not os.path.isfile(os.path.join(info_dir, "has_prefix"))
