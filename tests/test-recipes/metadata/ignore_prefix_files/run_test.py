import os

pkgs = os.path.join(os.environ["ROOT"], "pkgs")
info_dir = os.path.join(pkgs, "conda-build-test-ignore-prefix-files-1.0-0", "info")
assert os.path.isdir(info_dir)
assert not os.path.isfile(os.path.join(info_dir, "has_prefix"))
