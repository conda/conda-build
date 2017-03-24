import os

import pytest

from conda_build import api
from conda_build.utils import conda_43

thisdir = os.path.dirname(os.path.abspath(__file__))


@pytest.mark.skipif(conda_43(), reason="conda 4.3 removed sign support")
def test_import_sign_key():
    api.import_sign_key(os.path.join(thisdir, 'test_key'))
    keypath = os.path.expanduser("~/.conda/keys/test_key")
    try:
        assert os.path.isfile(keypath)
        assert os.path.isfile(keypath + '.pub')
    except:
        raise
    finally:
        os.remove(keypath)
        os.remove(keypath + '.pub')
