from conda_build.license_family import guess_license_family, deprecated_guess_license_family


def test_guess_license_family_matching():
    cens = "GPL"
    fam = guess_license_family(cens)
    assert fam == 'GPL'
    prev = deprecated_guess_license_family(cens)
    assert fam != prev, 'new and deprecated guesses are unexpectedly the same'
    assert prev == 'GPL3'  # bizarre when GPL is an allowed license family

    cens = "GPL (>= 3)"
    fam = guess_license_family(cens)
    assert fam == 'GPL3'
    prev = deprecated_guess_license_family(cens)
    assert fam == prev, 'new and deprecated guesses differ'

    cens = 'GNU Lesser General Public License'
    fam = guess_license_family(cens)
    assert fam == 'LGPL', 'guess_license_family({}) is {}'.format(cens, fam)
    prev = deprecated_guess_license_family(cens)
    assert fam == prev, 'new and deprecated guesses differ'

    cens = 'GNU General Public License some stuff then a 3 then stuff'
    fam = guess_license_family(cens)
    assert fam == 'GPL3', 'guess_license_family({}) is {}'.format(cens, fam)
    prev = deprecated_guess_license_family(cens)
    assert fam == prev, 'new and deprecated guesses differ'

    cens = 'Affero GPL'
    fam = guess_license_family(cens)
    assert fam == 'AGPL', 'guess_license_family({}) is {}'.format(cens, fam)
    prev = deprecated_guess_license_family(cens)
    assert fam == prev, 'new and deprecated guesses differ'

    cens = u'GPL-2 | GPL-3 | file LICENSE'
    fam = guess_license_family(cens)
    assert fam == 'GPL3', 'guess_license_family_from_index({}) is {}'.format(cens, fam)
    prev = deprecated_guess_license_family(cens)
    assert fam != prev, 'new and deprecated guesses are unexpectedly the same'
    # Somehow PUBICDOMAIN is closer to cens than GPL2 or GPL3
    assert prev == 'PUBLICDOMAIN'

if __name__ == '__main__':
    test_guess_license_family_matching()
