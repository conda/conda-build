import os

from conda_build import api


def test_update_index(testing_workdir):
    api.update_index(testing_workdir)
    files = "repodata.json", "repodata.json.bz2"
    for f in files:
        assert os.path.isfile(os.path.join(testing_workdir, 'noarch', f))
