from conda_build.license_family import guess_license_family, allowed_license_families, ensure_valid_license_family
import pytest


def test_new_vs_previous_guesses_match():
    """Test cases where new and deprecated functions match"""

    cens = "GPL (>= 3)"
    fam = guess_license_family(cens)
    assert fam == 'GPL3'

    cens = 'GNU Lesser General Public License'
    fam = guess_license_family(cens)
    assert fam == 'LGPL', f'guess_license_family({cens}) is {fam}'

    cens = 'GNU General Public License some stuff then a 3 then stuff'
    fam = guess_license_family(cens)
    assert fam == 'GPL3', f'guess_license_family({cens}) is {fam}'

    cens = 'Affero GPL'
    fam = guess_license_family(cens)
    assert fam == 'AGPL', f'guess_license_family({cens}) is {fam}'


def test_new_vs_previous_guess_differ_gpl():
    """Test cases where new and deprecated functions differ

    license = 'GPL'
    New guess is GPL, which is an allowed family, hence the most accurate.
    Previously, GPL3 was chosen over GPL
    """
    cens = "GPL"
    fam = guess_license_family(cens)
    assert fam == 'GPL'


def test_new_vs_previous_guess_differ_multiple_gpl():
    """Test cases where new and deprecated functions differ

    license = 'GPL-2 | GPL-3 | file LICENSE'
    New guess is GPL-3, which is the most accurate.
    Previously, somehow Public-Domain is closer than GPL2 or GPL3!
    """
    cens = 'GPL-2 | GPL-3 | file LICENSE'
    fam = guess_license_family(cens)
    assert fam == 'GPL3', f'guess_license_family_from_index({cens}) is {fam}'


def test_old_warnings_no_longer_fail():
    # the following previously threw warnings. Came from r/linux-64
    warnings = {'MIT License', 'GNU Lesser General Public License (LGPL)',
         'GPL-2 | GPL-3 | file LICENSE', 'GPL (>= 3) | file LICENCE',
         'BSL-1.0', 'GPL (>= 2)', 'file LICENSE (FOSS)',
         'Open Source (http://www.libpng.org/pub/png/src/libpng-LICENSE.txt)',
         'MIT + file LICENSE', 'GPL-2 | GPL-3', 'GPL (>= 2) | file LICENSE',
         'Unlimited', 'GPL-3 | file LICENSE',
         'GNU General Public License v2 or later (GPLv2+)', 'LGPL-2.1',
         'LGPL-2', 'LGPL-3', 'GPL',
         'zlib (http://zlib.net/zlib_license.html)',
         'Free software (X11 License)', 'Custom free software license',
         'Old MIT', 'GPL 3', 'Apache License (== 2.0)', 'GPL (>= 3)', None,
         'LGPL (>= 2)', 'BSD_2_clause + file LICENSE', 'GPL-3', 'GPL-2',
         'BSD License and GNU Library or Lesser General Public License (LGPL)',
         'GPL-2 | file LICENSE', 'BSD_3_clause + file LICENSE', 'CC0',
         'MIT + file LICENSE | Unlimited', 'Apache License 2.0',
         'BSD License', 'Lucent Public License'}

    for cens in warnings:
        fam = guess_license_family(cens)
        print(f'{cens}:{fam}')
        assert fam in allowed_license_families


def test_gpl2():
    licenses = {'GPL-2', 'GPL-2 | file LICENSE',
                'GNU General Public License v2 or later (GPLv2+)'}
    for cens in licenses:
        fam = guess_license_family(cens)
        assert fam == 'GPL2'


def test_not_gpl2():
    licenses = {'GPL (>= 2)', 'LGPL (>= 2)', 'GPL',
                'LGPL-3', 'GPL 3', 'GPL (>= 3)',
                'Apache License (== 2.0)'}
    for cens in licenses:
        fam = guess_license_family(cens)
        assert fam != 'GPL2'


def test_gpl3():
    licenses = {'GPL 3', 'GPL-3', 'GPL-3 | file LICENSE',
                'GPL-2 | GPL-3 | file LICENSE', 'GPL (>= 3) | file LICENCE',
                'GPL (>= 2)', 'GPL-2 | GPL-3', 'GPL (>= 2) | file LICENSE'}
    for cens in licenses:
        fam = guess_license_family(cens)
        assert fam == 'GPL3'


def test_lgpl():
    licenses = {'GNU Lesser General Public License (LGPL)', 'LGPL-2.1',
                'LGPL-2', 'LGPL-3', 'LGPL (>= 2)',
                'BSD License and GNU Library or Lesser General Public License (LGPL)'}
    for cens in licenses:
        fam = guess_license_family(cens)
        assert fam == 'LGPL'


def test_mit():
    licenses = {'MIT License', 'MIT + file LICENSE', 'Old MIT'}
    for cens in licenses:
        fam = guess_license_family(cens)
        assert fam == 'MIT'


def test_unlimited():
    """The following is an unfortunate case where MIT is in UNLIMITED

    We could add words to filter out, but it would be hard to keep track of...
    """
    cens = 'Unlimited'
    assert guess_license_family(cens) == 'MIT'


def test_cc():
    fam = guess_license_family('CC0')
    assert fam == 'CC'


def test_other():
    licenses = {'file LICENSE (FOSS)',
                'Open Source (http://www.libpng.org/pub/png/src/libpng-LICENSE.txt)',
                'zlib (http://zlib.net/zlib_license.html)',
                'Free software (X11 License)', 'Custom free software license'}
    for cens in licenses:
        fam = guess_license_family(cens)
        assert fam == 'OTHER'


def test_ensure_valid_family(testing_metadata):
    testing_metadata.meta['about']['license_family'] = 'public-domain'
    ensure_valid_license_family(testing_metadata.meta)
    with pytest.raises(RuntimeError):
        testing_metadata.meta['about']['license_family'] = 'local H'
        ensure_valid_license_family(testing_metadata.meta)
