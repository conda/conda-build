import os

pkgs = os.path.join(os.environ["ROOT"], "pkgs")
package_dir_name = "conda-build-test-ignore-prefix-files-1.0-0"
info_dir = os.path.join(pkgs, package_dir_name, "info")

if not os.path.isdir(info_dir):
    channel_name = os.path.basename(os.path.dirname(os.path.dirname(os.environ["PREFIX"])))
    print("channel_name: %s" % channel_name)
    info_dir = os.path.join(pkgs, channel_name, os.environ["SUBDIR"], package_dir_name, "info")
    print(info_dir)
    if not os.path.isdir(info_dir):
        raise RuntimeError("No info_dir found: %s" % info_dir)

assert os.path.isdir(info_dir)
assert not os.path.isfile(os.path.join(info_dir, "has_prefix"))
