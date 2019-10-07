# -*- coding: utf-8 -*-
# Copyright (C) 2019 Anaconda, Inc
# SPDX-License-Identifier: ❓UNDETERMINED

# Python2 Compatibility
from __future__ import absolute_import, division, print_function, unicode_literals

# Standard libraries
import os
import os.path
import copy
import datetime
import json
import sys # for Python version checking, for strings
import binascii # for Python2/3-compatible hex string <- -> bytes conversion

# Dependency-provided libraries
import cryptography
import cryptography.exceptions
import cryptography.hazmat.primitives.asymmetric.ed25519 as ed25519
import cryptography.hazmat.primitives.serialization as serialization
import cryptography.hazmat.primitives.hashes
import cryptography.hazmat.backends

# conda imports
# TODO: ✅Use a relative import here to conform to conda's apparent practices.
from conda_build.conda_interface import SignatureError


# The only types we're allowed to wrap as "signables" and sign are
# the JSON-serializable types.  (There are further constraints to what is
# JSON-serializable in addition to these type constraints.)
SUPPORTED_SERIALIZABLE_TYPES = [
        dict, list, tuple, str, int, float, bool, type(None)]

# Default expiration distance for repodata_verify.json.
REPODATA_VERIF_MD_EXPIRY_DISTANCE = datetime.timedelta(days=31)

# specification version for the metadata produced here
SECURITY_METADATA_SPEC_VERSION = '0.0.5'


def sha512256(data):
    """
    Since hashlib still does not provide a "SHA-512/256" option (SHA-512 with,
    basically, truncation to 256 bits at each stage of the hashing, defined by
    the FIPS Secure Hash Standard), we provide it here.  SHA-512/256 is as
    secure as SHA-256, but substantially faster on 64-bit architectures.
    Uses pyca/cryptography.

    Given bytes, returns the hex digest of the hash of the given bytes, using
    SHA-512/256.
    """
    if not isinstance(data, bytes):
        # Note that string literals in Python2 also pass this test by default.
        # unicode_literals fixes that for string literals created in modules
        # importing unicode_literals.
        raise TypeError('Expected bytes; received ' + str(type(data)))

    # pyca/cryptography's interface is a little clunky about this.
    hasher = cryptography.hazmat.primitives.hashes.Hash(
            algorithm=cryptography.hazmat.primitives.hashes.SHA512_256(),
            backend=cryptography.hazmat.backends.default_backend())
    hasher.update(data)

    return hasher.finalize().hex()



def build_repodata_verification_metadata(
        repodata_hashmap, channel=None, expiry=None, timestamp=None):
    """
    # TODO: ✅ Full docstring.

    Note that if expiry or timestamp are not provided or left as None, now is
    used for the timestamp, and expiry is produced using a default expiration
    distance, via set_expiry().  (It does not mean no expiration!)

    Sample input (repodata_hashmap):
    {
        "noarch/current_repodata.json": "908724926552827ab58dfc0bccba92426cec9f1f483883da3ff0d8664e18c0fe",
        "noarch/repodata.json": "...",
        "noarch/repodata_from_packages.json": "...",
        "osx-64/current_repodata.json": "...",
        "osx-64/repodata.json": "...",
        "osx-64/repodata_from_packages.json": "..."
    }

    Sample output:
        See metadata specification (version defined by
        SECURITY_METADATA_SPEC_VERSION) for definition and samples of type
        "Repodata Verification Metadata".
    """

    # TODO: ✅ Argument validation


    if expiry is None:
        expiry = set_expiry(REPODATA_VERIF_MD_EXPIRY_DISTANCE)

    if timestamp is None:
        timestamp = set_expiry(datetime.timedelta(0))

    rd_v_md = {
            'type': 'repodata_verify',
            # (Take advantage of set_expiry() to get current time in the
            #  ISO8601 UTC format we want.)
            'timestamp': timestamp, # version->timestamp in spec v 0.0.5
            'metadata_spec_version': SECURITY_METADATA_SPEC_VERSION,
            'expiration': expiry,
            'secured_files': repodata_hashmap}

    if channel is not None:
        rd_v_md['channel'] = channel

    return rd_v_md



def set_expiry(delta):
    """
    Applies a datetime.timedelta to the current time in UTC with microseconds
    stripped, then converts to ISO8601 format and appends a 'Z' indicating that
    it is UTC time, not local time.  We only deal with UTC times!
    (This is also used to get current time in ISO8601 format, by passing in
    a 0 timedelta.)

    regex for time: '\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z'

    """
    if not isinstance(delta, datetime.timedelta):
        raise TypeError(
                'Expected a datetime.timedelta, got a ' + str(type(delta)))

    unix_expiry = datetime.datetime.utcnow().replace(microsecond=0) + delta

    return unix_expiry.isoformat() + 'Z'



def gen_and_write_keys(fname):
    """
    Generate an ed25519 key pair, then write the key files to disk.

    Given fname, write the private key to fname.pri, and the public key to
    fname.pub. Performs no filename validation, etc.  Also returns the private
    key object and the public key object, in that order.
    """

    # Create an ed25519 key pair, employing OS random generation.
    # Note that this just has the private key sitting around.  In the real
    # implementation, we'll want to use an HSM equipped with an ed25519 key.
    private, public = gen_keys()

    # Get the actual bytes of the key values.... Note that we're just grabbing
    # the not-encrypted private key value.
    private_bytes = key_to_bytes(private)
    public_bytes = key_to_bytes(public)

    with open(fname + '.pri', 'wb') as fobj:
            fobj.write(private_bytes)
    with open(fname + '.pub', 'wb') as fobj:
            fobj.write(public_bytes)

    return private, public



def gen_keys():
    """
    Generate an ed25519 key pair and return it (private key, public key).

    Returns Ed25519PrivateKey and Ed25519PublicKey objects (classes from
    cryptography.hazmat.primitives.asymmetric.ed25519).
    """
    # Create an ed25519 key pair, employing OS random generation.
    # Note that this just has the private key sitting around.  In the real
    # implementation, we'll want to use an HSM equipped with an ed25519 key.
    private = ed25519.Ed25519PrivateKey.generate()
    public = private.public_key()

    return private, public



def keyfiles_to_bytes(name):
    """
    Toy function.  Import an ed25519 key pair, in the forms of raw public and
    raw private keys, from name.pub and name.pri respectively.

    Cavalier about private key bytes.
    Does not perform input validation ('/'...).

    Return the 32 bytes of the private key object and the 32 bytes of the
    public key object, in that order.
    """
    with open(name + '.pri', 'rb') as fobj:
            private_bytes = fobj.read()

    with open(name + '.pub', 'rb') as fobj:
            public_bytes = fobj.read()

    return private_bytes, public_bytes



def keyfiles_to_keys(name):
    """
    Doesn't perform input validation.
    Import an ed25519 key pair, in the forms of raw public key
    bytes and raw private key bytes, from name.pub and name.pri respectively.
    Cavalier about private key bytes.
    Return a private key object and public key object, in that order.
    """
    private_bytes, public_bytes = keyfiles_to_bytes(name)

    private = private_key_from_bytes(private_bytes)
    public = public_key_from_bytes(public_bytes)

    return private, public



def key_to_bytes(key):
    """
    Pops out the nice, tidy bytes of a given cryptography...ed25519 key obj,
    public or private.
    """
    if isinstance(key, ed25519.Ed25519PrivateKey):
        return key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption())
    elif isinstance(key, ed25519.Ed25519PublicKey):
        return key.public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw)
    else:
        raise TypeError(
                'Can only handle objects of class Ed25519PrivateKey or '
                'Ed25519PublicKey.  Given object is of class: ' +
                str(type(key)))



def public_key_from_bytes(public_bytes):
    return ed25519.Ed25519PublicKey.from_public_bytes(public_bytes)


# def public_key_from_hexstring(public_hexstring):
#     return ed25519.Ed25519PublicKey.from_public_bytes(binascii.unhexlify(public_hexstring))



def private_key_from_bytes(private_bytes):
    return ed25519.Ed25519PrivateKey.from_private_bytes(private_bytes)



def keys_are_equivalent(k1, k2):
    """
    Given Ed25519PrivateKey or Ed25519PublicKey objects, determines if the
    underlying key data is identical.
    """
    return key_to_bytes(k1) == key_to_bytes(k2)



# TODO: ✅ Invert argument order.
def sign(private_key, data):
    """
    We'll actually be using an HSM to do the signing, so we won't have access
    to the actual private key.  But for now....
    Create an ed25519 signature over data using private_key.
    Return the bytes of the signature.
    Not doing input validation, but:
    - private_key should be an Ed25519PrivateKey obj.
    - data should be bytes

    Note that this process is deterministic AND does not depend at any point on
    the ability to generate random data (unlike the key generation).

    The returned value is bytes, length 64, raw ed25519 signature.
    """
    return private_key.sign(data)



# TODO: ✅ Invert argument order.
def serialize_and_sign(private_key, obj):
    """
    Given a JSON-compatible object, does the following:
     - serializes the dictionary as utf-8-encoded JSON, lazy-canonicalized
       such that any dictionary keys in any dictionaries inside <dictionary>
       are sorted and indentation is used and set to 2 spaces (using json lib)
     - creates a signature over that serialized result using private_key
     - returns that signature

    See comments in canonserialize()
    """

    # Try converting to a JSON string.
    serialized = canonserialize(obj)

    return sign(private_key, serialized)



def canonserialize(obj):
    """
    Canonicalize and then serialize.
    Given a JSON-compatible object, does the following:
     - serializes the dictionary as utf-8-encoded JSON, lazy-canonicalized
       such that any dictionary keys in any dictionaries inside <dictionary>
       are sorted and indentation is used and set to 2 spaces (using json lib)

    TODO: ✅ Implement the serialization checks from serialization document.
    """

    # Try converting to a JSON string.
    try:
        # TODO: In the future, assess whether or not to employ more typical
        #       practice of using no whitespace (instead of NLs and 2-indent).
        json_string = json.dumps(obj, indent=2, sort_keys=True)
    except TypeError:
        # TODO: ✅ Log or craft/use an appropriate exception class.
        raise

    return json_string.encode('utf-8')



def wrap_as_signable(obj):
    """
    Given a JSON-serializable object (dictionary, list, string, numeric, etc.),
    returns a wrapped copy of that object:

        {'signatures': {},
         'signed': <deep copy of the given object>}

    Expects strict typing matches (not duck typing), for no good reason.
    (Trying JSON serialization repeatedly could be too time consuming.)

    TODO: ✅ Consider whether or not the copy can be shallow instead, for speed.

    Raises ❌TypeError if the given object is not a JSON-serializable type per
    SUPPORTED_SERIALIZABLE_TYPES
    """
    if not type(obj) in SUPPORTED_SERIALIZABLE_TYPES:
        raise TypeError(
                'wrap_dict_as_signable requires a JSON-serializable object, '
                'but the given argument is of type ' + str(type(obj)) + ', '
                'which is not supported by the json library functions.')

    # TODO: ✅ Later on, consider switching back to TUF-style
    #          signatures-as-a-list.  (Is there some reason it's saner?)
    #          Going with my sense of what's best now, which is dicts instead.
    #          It's simpler and it naturally avoids duplicates.  We don't do it
    #          this way in TUF, but we also don't depend on it being an ordered
    #          list anyway, so a dictionary is probably better.

    return {'signatures': {}, 'signed': copy.deepcopy(obj)}



def is_a_signable(dictionary):
    """
    Returns True if the given dictionary is a signable dictionary as produced
    by wrap_as_signable.  Note that there MUST be no additional elements beyond
    'signed' and 'signable' in the dictionary.  (The only data in the envelope
    outside the signed portion of the data should be the signatures; what's
    outside of 'signed' is under attacker control.)
    """
    if (isinstance(dictionary, dict)
            and 'signatures' in dictionary
            and 'signed' in dictionary
            and isinstance(dictionary['signatures'], dict) #, list)
            and type(dictionary['signed']) in SUPPORTED_SERIALIZABLE_TYPES
            and len(dictionary) == 2
            ):
        return True

    else:
        return False


def is_hex_signature(sig):
    """
    Returns True if sig is a hex string with no uppercase characters, no spaces,
    etc., and is of the correct length for an ed25519 signature, 64 bytes of
    raw data represented as 128 hexadecimal characters.  Else, returns False.
    """
    if not _is_hex_string(sig):
        return False

    if len(sig) != 128:
        return False

    return True



def is_hex_string_pubkey(key):
    """
    Returns True if key is a hex string with no uppercase characters, no spaces,
    etc., and is of the correct length for an ed25519 key, 32 bytes of raw
    data represented as 64 hexadecimal characters.  Else, returns False.
    """
    if not _is_hex_string(key):
        return False

    if len(key) != 64:
        return False

    return True



def _is_hex_string(s):
    """
    Returns True if hex is a hex string with no uppercase characters, no spaces,
    etc.  Else, False.
    """
    if sys.version_info.major < 3:
        if not isinstance(s, unicode):
            return False
    elif not isinstance(s, str):
        return False

    for c in s:
        if c not in [
                '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0',
                'a', 'b', 'c', 'd', 'e', 'f']:
            return False

    return True



def sign_signable(signable, private_key):
    """
    Given a JSON-compatible signable dictionary (as produced by calling
    wrap_dict_as_signable with a JSON-compatible dictionary), calls
    serialize_and_sign on the enclosed dictionary at signable['signed'],
    producing a signature, and places the signature in
    signable['signatures'], in an entry indexed by the public key
    corresponding to the given private_key.

    Updates the given signable in place, returning nothing.
    Overwrites if there is already an existing signature by the given key.

    Unlike with lower-level functions, both signatures and public keys are
    always written as hex strings.

    Raises ❌TypeError if the given object is not a JSON-serializable type per
    SUPPORTED_SERIALIZABLE_TYPES
    """
    # Argument checking
    if not is_a_signable(signable):
        raise TypeError(
                'Expected a signable dictionary; the given argument of type ' +
                str(type(signable)) + ' failed the check.')

    signature = serialize_and_sign(private_key, signable['signed'])

    signature_as_hexstr = binascii.hexlify(signature).decode('utf-8')

    public_key_as_hexstr = binascii.hexlify(key_to_bytes(
            private_key.public_key())).decode('utf-8')


    # TODO: ✅⚠️ Log a warning in whatever conda's style is (or conda-build):
    #
    # if public_key_as_hexstr in signable['signatures']:
    #   warn(    # replace: log, 'warnings' module, print statement, whatever
    #           'Overwriting existing signature by the same key on given '
    #           'signable.  Public key: ' + public_key + '.')

    # Add signature in-place.
    signable['signatures'][public_key_as_hexstr] = signature_as_hexstr



def verify_signature(signature, public_key, data):
    """
    Raises ❌cryptography.exceptions.InvalidSignature if signature is not a
    correct signature by the given key over the given data.

    Raises ❌TypeError if public_key, signature, or data are not correctly
    formatted.

    Otherwise, returns (nothing), indicating the signature was verified.

    Args:
        - public_key must be an ed25519.Ed25519PublicKeyObject
        - signature must be bytes, length 64
        - data must be bytes
    """
    if not isinstance(public_key, ed25519.Ed25519PublicKey):
        raise TypeError(
                'verify_signature expects a '
                'cryptography.hazmat.primitives.asymmetric.ed25519ed25519.Ed25519PublicKey'
                'object as the "public_key" argument.  Instead, received ' +
                str(type(public_key)))

    if not isinstance(signature, bytes) or 64 != len(signature):
        raise TypeError(
                'verify_signature expects a bytes object as the "signature" '
                'argument. Instead, received ' + str(type(signature)))

    if not isinstance(data, bytes):
        raise TypeError(
                'verify_signature expects a bytes object as the "signature" '
                'argument.  Instead, received ' + str(type(data)))

    public_key.verify(signature, data)

    # If no error is raised, return, indicating success (Explicit for editors)
    return




def verify_signable(signable, authorized_pub_keys, threshold):
    """
    Raises a ❌SignatureError if signable does not include at least threshold
    good signatures from (unique) keys with public keys listed in
    authorized_pub_keys, over the data contained in signable['signed'].

    Raises ❌TypeError if the arguments are invalid.

    Else returns (nothing).

    Args:
        - signable
            is_a_signable(signable) must return true.  wrap_as_signable()
            produces output of this type.  See those functions.

        - authorized_pub_keys
            a list of ed25519 public keys (32 bytes) expressed as 64-character
            hex strings.  This is the form in which they appear in authority
            metadata (root.json, etc.)  Only good signatures from keys listed
            in authorized_pub_keys count against the threshold of signatures
            required to verify the signable.

        - threshold
            the number of good signatures from unique authorized keys required
            in order to verify the signable.
    """

    # TODO: ✅ Be sure to check with the analogous code in the tuf reference
    #       implementation in case one of us had some clever gotcha there.
    #       Would be in tuf.sig or securesystemslib.  See
    #       get_signature_status() there, in addition to any prettier
    #       verify_signable code I may have swapped in (dunno if that's in yet).

    # TODO: ✅ Consider allowing this func (or another) to accept public keys
    #       in the form of ed25519.Ed25519PublicKey objects (instead of just
    #       the hex string representation of the public key bytes).  I think
    #       we'll mostly have the hex strings on hand, but....

    # Argument validation
    if not is_a_signable(signable):
        raise TypeError(
                'verify_signable expects a signable dictionary.  '
                'Given argument failed the test.') # TODO: Tidier / expressive.
    if not (isinstance(authorized_pub_keys, list) and all(
            [is_hex_string_pubkey(k) for k in authorized_pub_keys])):
        raise TypeError('authorized_pub_keys must be a list of hex strings ')
    # if not (isinstance(authorized_pub_keys, list) and all(
    #         [isinstance(k, ed25519.Ed25519PublicKey) for k in authorized_pub_keys])):
    #     raise TypeError(
    #             'authorized_pub_keys must be a list of '
    #             'ed25519.Ed25519PublicKeyobjects.')
    if not isinstance(threshold, int) or threshold <= 0:
        raise TypeError('threshold must be a positive integer.')


    # TODO: ✅⚠️ Metadata specification version compatibility check.
    #             Check to see if signable['signed']['metadata_spec_version']
    #             is CLOSE ENOUGH to SECURITY_METADATA_SPEC_VERSION (same
    #             major version?).  If it is not, raise an exception noting
    #             that the version cannot be verified because either it or the
    #             client are out of date.  If versions are close enough,
    #             consider a warning instead.  If the client is at major spec
    #             version x, and the metadata obtained is at major spec version
    #             x + 1, then proceed with a warning that the client must be
    #             updated.  Note that root versions produced must never
    #             increase by more than one major spec version at a time, as a
    #             result.

    # Put the 'signed' portion of the data into the format it should be in
    # before it is signed, so that we can verify the signatures.
    signed_data = canonserialize(signable['signed'])

    # Even though we're not returning this, we produce this dictionary (instead
    # of just counting) to facilitate future checks and logging.
    # TODO: ✅ Keep track of unknown keys and bad signatures for diagnostic and
    #          other logging purposes.
    good_sigs_from_trusted_keys = {}

    for pubkey_hex, signature in signable['signatures'].items():

        if pubkey_hex not in authorized_pub_keys:
            continue

        public = public_key_from_bytes(binascii.unhexlify(pubkey_hex))

        try:
            verify_signature(
                    binascii.unhexlify(signature),
                    public,
                    signed_data)

        except cryptography.exceptions.InvalidSignature:
            # TODO: Log.
            continue

        else:
            good_sigs_from_trusted_keys[pubkey_hex] = signature


    # TODO: ✅ Logging or more detailed info (which keys).
    if len(good_sigs_from_trusted_keys) < threshold:
        raise SignatureError(
                'Expected good signatures from at least ' + str(threshold) +
                'unique keys from a set of ' + str(len(authorized_pub_keys)) +
                'keys.  Saw ' + str(len(signable['signatures'])) +
                ' signatures, only ' + str(len(good_sigs_from_trusted_keys)) +
                ' of which were good signatures over the given data from the '
                'expected keys.')

    # Otherwise, return, indicating success.  (Explicit for code editors)
    return
