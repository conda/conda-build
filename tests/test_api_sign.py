import os

from conda_build import api

thisdir = os.path.dirname(os.path.abspath(__file__))


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
