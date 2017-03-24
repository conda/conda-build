from glob import glob
import os

pkgs = os.path.join(os.environ["ROOT"], "pkgs")
pkg_dir = glob(os.path.join(pkgs, "conda-build-test-ignore-some-prefix-files-1.0-h*_0"))[0]
info_dir = os.path.join(pkg_dir, 'info')
has_prefix_file = os.path.join(info_dir, "has_prefix")
print(info_dir)
assert os.path.isfile(has_prefix_file)
with open(has_prefix_file) as f:
    assert "test2" not in f.read()
