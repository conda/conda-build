import sys

import pytest

from conda_build import api


def test_inspect_linkages():
    if sys.platform == 'win32':
        with pytest.raises(SystemExit) as exc:
            out_string = api.inspect_linkages("python")
            assert 'conda inspect linkages is only implemented in Linux and OS X' in exc
    else:
        out_string = api.inspect_linkages("python")
        assert 'openssl' in out_string


def test_inspect_objects():
    if sys.platform != 'darwin':
        with pytest.raises(SystemExit) as exc:
            out_string = api.inspect_objects("python")
            assert 'conda inspect objects is only implemented in OS X' in exc
    else:
        out_string = api.inspect_objects("python")
        assert 'rpath: @loader_path' in out_string


def test_channel_installable():
    # make sure the default channel is installable as a reference
    assert api.test_installable('conda-team')

#     # create a channel that is not installable to validate function

#     platform = os.path.join(testing_workdir, subdir)
#     output_file = os.path.join(platform, "empty_sections-0.0-0.tar.bz2")

#     # create the index so conda can find the file
#     api.update_index(platform)

#     assert not api.test_installable(channel=to_url(testing_workdir))
