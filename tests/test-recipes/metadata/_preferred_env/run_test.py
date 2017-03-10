from glob import glob
import json
import os

pkgs_dir = os.path.abspath(os.path.join(os.environ["ROOT"], 'pkgs'))
pkg_dir = glob(os.path.join(pkgs_dir, "preferred_env_test_package-1.0-h*_0"))[0]

with open(os.path.join(pkg_dir, 'info', 'index.json')) as fh:
    index_json = json.loads(fh.read())
assert index_json['preferred_env'] == "_env_"
