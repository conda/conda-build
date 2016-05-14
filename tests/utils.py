import os
import sys

thisdir = os.path.dirname(os.path.realpath(__file__))
metadata_dir = os.path.join(thisdir, "test-recipes/metadata")
fail_dir = os.path.join(thisdir, "test-recipes/fail")


def is_valid_dir(parent_dir, dirname):
    valid = os.path.isdir(os.path.join(parent_dir, dirname))
    valid &= not dirname.startswith("_")
    valid &= ('osx_is_app' != dirname or sys.platform == "darwin")
    return valid
