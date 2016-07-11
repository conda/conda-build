import os

import pytest

from conda_build import api
from .utils import testing_workdir

repo_packages = [('', 'pypi', 'pip'),
                 ('r', 'cran', 'nmf'),
                 ('perl', 'cpan', 'Struct-Path'),
                 # ('lua', luarocks', 'LuaSocket'),
                 ]


@pytest.mark.parametrize("prefix,repo,package", repo_packages)
def test_skeletonize_specific_repo(prefix, repo, package, testing_workdir):
    api.skeletonize(package, output_dir=testing_workdir, repo=repo)
    try:
        package_name = "-".join([prefix, package]) if prefix else package
        assert os.path.isdir(os.path.join(testing_workdir, package_name.lower()))
    except:
        print(os.listdir(testing_workdir))
        raise
