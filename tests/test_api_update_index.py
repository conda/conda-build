import os

from conda_build import api


def test_update_index(testing_workdir, testing_config):
    api.update_index(testing_workdir, testing_config)
    files = ".index.json", "repodata.json", "repodata.json.bz2"
    for f in files:
        assert os.path.isfile(os.path.join(testing_workdir, f))
