import sys

import pytest

from conda_build import api
from .utils import testing_workdir

def test_inspect_linkages():
    pass


pytest.mark.skipif(sys.platform != "darwin",
                   reason="object inspection only implemented for mac.")
def test_inspect_objects():
    pass


def test_channel_installable(testing_workdir):
    # make sure the default channel is installable as a reference
    assert api.test_installable()

    # create a channel that is not installable to validate function

    platform = os.path.join(testing_workdir, subdir)
    output_file = os.path.join(platform, "empty_sections-0.0-0.tar.bz2")

    # create the index so conda can find the file
    api.update_index(platform)

    assert not api.test_installable(channel=to_url(testing_workdir))
