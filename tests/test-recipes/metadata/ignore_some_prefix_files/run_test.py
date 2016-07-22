import os
import sys

# assumes that sys.prefix is <root>/envs/_test
pkgs = os.path.normpath(os.path.join(sys.prefix, "..", "..", "..", "pkgs"))
info_dir = os.path.join(pkgs, "conda-build-test-ignore-some-prefix-files-1.0-0", "info")
has_prefix_file = os.path.join(info_dir, "has_prefix")
print(info_dir)
assert os.path.isfile(has_prefix_file)
with open(has_prefix_file) as f:
    assert "test2" not in f.read()
