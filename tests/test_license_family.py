from conda_build.license_family import guess_license_family, allowed_license_families


def test_new_vs_previous_guesses_match():
    """Test cases where new and deprecated functions match"""

    cens = "GPL (>= 3)"
    fam = guess_license_family(cens)
    assert fam == 'GPL3'

    cens = 'GNU Lesser General Public License'
    fam = guess_license_family(cens)
    assert fam == 'LGPL', 'guess_license_family({}) is {}'.format(cens, fam)

    cens = 'GNU General Public License some stuff then a 3 then stuff'
    fam = guess_license_family(cens)
    assert fam == 'GPL3', 'guess_license_family({}) is {}'.format(cens, fam)

    cens = 'Affero GPL'
    fam = guess_license_family(cens)
    assert fam == 'AGPL', 'guess_license_family({}) is {}'.format(cens, fam)


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
    cens = u'GPL-2 | GPL-3 | file LICENSE'
    fam = guess_license_family(cens)
    assert fam == 'GPL3', 'guess_license_family_from_index({}) is {}'.format(cens, fam)


def test_old_warnings_no_longer_fail():
    # the following previously threw warnings. Came from r/linux-64
    warnings = {u'MIT License', u'GNU Lesser General Public License (LGPL)',
         u'GPL-2 | GPL-3 | file LICENSE', u'GPL (>= 3) | file LICENCE',
         u'BSL-1.0', u'GPL (>= 2)', u'file LICENSE (FOSS)',
         u'Open Source (http://www.libpng.org/pub/png/src/libpng-LICENSE.txt)',
         u'MIT + file LICENSE', u'GPL-2 | GPL-3', u'GPL (>= 2) | file LICENSE',
         u'Unlimited', u'GPL-3 | file LICENSE',
         u'GNU General Public License v2 or later (GPLv2+)', u'LGPL-2.1',
         u'LGPL-2', u'LGPL-3', u'GPL',
         u'zlib (http://zlib.net/zlib_license.html)',
         u'Free software (X11 License)', u'Custom free software license',
         u'Old MIT', u'GPL 3', u'Apache License (== 2.0)', u'GPL (>= 3)', None,
         u'LGPL (>= 2)', u'BSD_2_clause + file LICENSE', u'GPL-3', u'GPL-2',
         u'BSD License and GNU Library or Lesser General Public License (LGPL)',
         u'GPL-2 | file LICENSE', u'BSD_3_clause + file LICENSE', u'CC0',
         u'MIT + file LICENSE | Unlimited', u'Apache License 2.0',
         u'BSD License', u'Lucent Public License'}

    for cens in warnings:
        fam = guess_license_family(cens)
        print('{}:{}'.format(cens, fam))
        assert fam in allowed_license_families


def test_gpl2():
    licenses = {u'GPL-2', u'GPL-2 | file LICENSE',
                u'GNU General Public License v2 or later (GPLv2+)'  }
    for cens in licenses:
        fam = guess_license_family(cens)
        assert fam == u'GPL2'


def test_not_gpl2():
    licenses = {u'GPL (>= 2)', u'LGPL (>= 2)', u'GPL',
                u'LGPL-3', u'GPL 3', u'GPL (>= 3)',
                u'Apache License (== 2.0)'}
    for cens in licenses:
        fam = guess_license_family(cens)
        assert fam != u'GPL2'


def test_gpl3():
    licenses = {u'GPL 3', u'GPL-3', u'GPL-3 | file LICENSE',
                u'GPL-2 | GPL-3 | file LICENSE', u'GPL (>= 3) | file LICENCE',
                u'GPL (>= 2)', u'GPL-2 | GPL-3', u'GPL (>= 2) | file LICENSE'}
    for cens in licenses:
        fam = guess_license_family(cens)
        assert fam == u'GPL3'


def test_lgpl():
    licenses = {u'GNU Lesser General Public License (LGPL)', u'LGPL-2.1',
                u'LGPL-2', u'LGPL-3', u'LGPL (>= 2)',
                u'BSD License and GNU Library or Lesser General Public License (LGPL)'}
    for cens in licenses:
        fam = guess_license_family(cens)
        assert fam == u'LGPL'


def test_mit():
    licenses = {u'MIT License', u'MIT + file LICENSE', u'Old MIT'}
    for cens in licenses:
        fam = guess_license_family(cens)
        assert fam == u'MIT'


def test_unlimited():
    """The following is an unfortunate case where MIT is in UNLIMITED

    We could add words to filter out, but it would be hard to keep track of...
    """
    cens = u'Unlimited'
    assert guess_license_family(cens) == 'MIT'


def test_other():
    licenses = {u'file LICENSE (FOSS)', u'CC0',
                u'Open Source (http://www.libpng.org/pub/png/src/libpng-LICENSE.txt)',
                u'zlib (http://zlib.net/zlib_license.html)',
                u'Free software (X11 License)', u'Custom free software license'}
    for cens in licenses:
        fam = guess_license_family(cens)
        assert fam == u'Other'
