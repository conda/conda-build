import base64
import os
from os.path import isdir, join
import shutil
import sys

try:
    from Crypto import Random
    from Crypto.PublicKey import RSA
    from Crypto.Signature import PKCS1_PSS
except ImportError:
    sys.exit("""\
Error: could not import Crypto (required for "conda sign").
    Run the following command:

    $ conda install -n root pycrypto
""")

from conda.signature import KEYS_DIR, hash_file


def keygen(name, size=2048):
    print("Generating public/private key pair (%d bits)..." % size)
    random_generator = Random.new().read
    key = RSA.generate(size, random_generator)

    if not isdir(KEYS_DIR):
        os.makedirs(KEYS_DIR)

    path = join(KEYS_DIR, name)
    print("Storing private key: %s" % path)
    with open(path, 'wb') as fo:
        fo.write(key.exportKey())
        fo.write(b'\n')
    os.chmod(path, 0o600)

    path = join(KEYS_DIR, '%s.pub' % name)
    print("Storing public key : %s" % path)
    with open(path, 'wb') as fo:
        fo.write(key.publickey().exportKey())
        fo.write(b'\n')


def import_key(private_key_path, new_name=None):
    """Import an existing private key for use with conda signing.
    This is not strictly necessary, but allows you to not specify the
    key every time when signing.
    """
    if not new_name:
        new_name = os.path.basename(private_key_path)
    shutil.copy(private_key_path, os.path.join(KEYS_DIR, new_name))
    with open(os.path.join(KEYS_DIR, new_name + ".pub")) as f:
        key = RSA.importKey(open(private_key_path).read())
        f.write(key.publickey().exportKey())


def get_default_keyname():
    if isdir(KEYS_DIR):
        for fn in os.listdir(KEYS_DIR):
            if not fn.endswith('.pub'):
                return fn
    return None


def sign(path, key_name_or_path=None):
    if not key_name_or_path:
        key_name_or_path = get_default_keyname()
        if not key_name_or_path:
            raise ValueError("Error: no private key found in %s" % KEYS_DIR)

    if not os.path.isfile(key_name_or_path) and os.path.isfile(join(KEYS_DIR, key_name_or_path)):
        key_name_or_path = join(KEYS_DIR, key_name_or_path)

    key = RSA.importKey(open(key_name_or_path).read())

    signer = PKCS1_PSS.new(key)
    sig = signer.sign(hash_file(path))
    return base64.b64encode(sig).decode('utf-8')


def sign_and_write(path, key_name_or_path):
    with open('%s.sig' % path, 'w') as fo:
        fo.write('%s ' % key_name_or_path)
        fo.write(sign(path, key_name_or_path))
        fo.write('\n')
