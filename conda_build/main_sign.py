# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

import sys
from os.path import isdir, join


def main():
    from conda.cli.conda_argparse import ArgumentParser

    p = ArgumentParser(
        description="""\
Tool for signing conda packages.  Signatures will be written alongside the
files as FILE.sig.""")

    p.add_argument('files',
        help="Files to sign.",
        nargs='*',
        metavar="FILE",)
    p.add_argument('-k', '--keygen',
                 action="store",
                 help="Generate a public-private "
                      "key pair ~/.conda/keys/<NAME>(.pub).",
                 metavar="NAME")
    p.add_argument('--size',
                 action="store",
                 help="Size of generated RSA public-private key pair in bits "
                      "(defaults to 2048).",
                 metavar="BITS")
    p.add_argument('-v', '--verify',
                 action="store_true",
                 help="Verify FILE(s).")

    args = p.parse_args()

    if args.keygen:
        if args.files:
            p.error('no arguments expected for --keygen')
        try:
            api.keygen(args.keygen, int(2048 if args.size is None else args.size))
        except ValueError as e:
            sys.exit('Error: %s' % e)
        return

    if args.size is not None:
        p.error('--size option is only allowed with --keygen option')

    if args.verify:
        for path in args.files:
            valid = api.verify(path)
            try:
                disp = 'VALID' if valid else 'INVALID'
            except SignatureError as e:
                disp = 'ERROR: %s' % e
            print('%-40s %s' % (path, disp))
        return

    key_name = get_default_keyname()
    if key_name is None:
        sys.exit("Error: no private key found in %s" % KEYS_DIR)
    print("Using private key '%s' for signing." % key_name)
    for path in args.files:
        print('signing: %s' % path)
        return api.sign(path, key_name)


if __name__ == '__main__':
    main()
