'''
Unit tests of the CRAN skeleton utility functions
'''


import os
import pytest

from conda_build.license_family import allowed_license_families
from conda_build.skeletons.cran import (get_license_info,
                                        read_description_contents,
                                        remove_comments)


thisdir = os.path.dirname(os.path.realpath(__file__))


# (license_string, license_id, license_family, license_files)
cran_licenses = [('GPL-3', 'GPL-3', 'GPL3',
                  'license_file:\n    - \'{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3\''),
                 ('Artistic License 2.0', 'Artistic-2.0', 'OTHER',
                  'license_file:\n    - \'{{ environ["PREFIX"] }}/lib/R/share/licenses/Artistic-2.0\''),
                 ('MPL-2.0', 'MPL-2.0', 'OTHER', ''),
                 ('MIT + file LICENSE', 'MIT', 'MIT',
                  'license_file:\n    - \'{{ environ["PREFIX"] }}/lib/R/share/licenses/MIT\'\n    - LICENSE'),
                 ('BSD 2-clause License + file LICENSE', 'BSD_2_clause', 'BSD',
                  'license_file:\n    - \'{{ environ["PREFIX"] }}/lib/R/share/licenses/BSD_2_clause\'\n    - LICENSE'),
                 ('GPL-2 | GPL-3', 'GPL-2 | GPL-3', 'GPL3',
                  'license_file:\n    - \'{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-2\'\n    - \'{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3\''),
                 ('GPL-3 | GPL-2', 'GPL-3 | GPL-2', 'GPL3',
                  'license_file:\n    - \'{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3\'\n    - \'{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-2\''),
                 ('GPL (>= 2)', 'GPL-2', 'GPL2',
                  'license_file:\n    - \'{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-2\''),
                 ]


@pytest.mark.parametrize("license_string, license_id, license_family, license_files", cran_licenses)
def test_get_license_info(license_string, license_id, license_family, license_files):
    observed = get_license_info(license_string, allowed_license_families)
    assert observed[0] == license_id
    assert observed[2] == license_family
    assert observed[1] == license_files


def test_read_description_contents():
    description = os.path.join(thisdir, 'test-cran-skeleton', 'rpart', 'DESCRIPTION')
    with open(description, 'rb') as fp:
        contents = read_description_contents(fp)
    assert contents['Package'] == 'rpart'
    assert contents['Priority'] == 'recommended'
    assert contents['Title'] == 'Recursive Partitioning and Regression Trees'
    assert contents['Depends'] == 'R (>= 2.15.0), graphics, stats, grDevices'
    assert contents['License'] == 'GPL-2 | GPL-3'
    assert contents['URL'] == 'https://github.com/bethatkinson/rpart, https://cran.r-project.org/package=rpart'


def test_remove_comments():
    example = '''
#!keep
# remove
  # remove
keep
keep # keep
'''
    expected = '''
#!keep
keep
keep # keep
'''
    observed = remove_comments(example)
    assert observed == expected
