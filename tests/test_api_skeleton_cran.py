'''
Integrative tests of the CRAN skeleton that start from
conda_build.api.skeletonize and check the output files
'''


import os
import pytest

from conda_build import api
from conda_build.skeletons.cran import CRAN_BUILD_SH_SOURCE, CRAN_META
from conda_build.utils import ensure_list


# CRAN packages to test license_file entry.
# (package, license_id, license_family, license_files)
cran_packages = [('r-rmarkdown', 'GPL-3', 'GPL3', 'GPL-3'),  # cran: 'GPL-3'
                 ('r-cortools', 'Artistic-2.0', 'OTHER', 'Artistic-2.0'),  # cran: 'Artistic License 2.0'
                 ('r-udpipe', 'MPL-2.0', 'OTHER', ''),  # cran: 'MPL-2.0'
                 ('r-broom', 'MIT', 'MIT', ['MIT', 'LICENSE']),  # cran: 'MIT + file LICENSE'
                 ('r-meanr', 'BSD_2_clause', 'BSD', ['BSD_2_clause', 'LICENSE']),  # cran: 'BSD 2-clause License + file LICENSE'
                 ('r-zoo', 'GPL-2 | GPL-3', 'GPL3', ['GPL-2', 'GPL-3']),  # cran: 'GPL-2 | GPL-3'
                 ('r-magree', 'GPL-3 | GPL-2', 'GPL3', ['GPL-3', 'GPL-2']),  # cran: 'GPL-3 | GPL-2'
                 ('r-mglm', 'GPL-2', 'GPL2', 'GPL-2'),  # cran: 'GPL (>= 2)'
                 ]


@pytest.mark.slow
@pytest.mark.parametrize("package, license_id, license_family, license_files", cran_packages)
@pytest.mark.flaky(max_runs=5)
def test_cran_license(package, license_id, license_family, license_files, testing_workdir, testing_config):
    api.skeletonize(packages=package, repo='cran', output_dir=testing_workdir,
                    config=testing_config)
    m = api.render(os.path.join(package, 'meta.yaml'))[0][0]
    m_license_id = m.get_value('about/license')
    assert m_license_id == license_id
    m_license_family = m.get_value('about/license_family')
    assert m_license_family == license_family
    m_license_files = ensure_list(m.get_value('about/license_file', ''))
    license_files = ensure_list(license_files)
    for m_license_file in m_license_files:
        assert os.path.basename(m_license_file) in license_files


# CRAN packages to test skip entry.
# (package, skip_text)
cran_os_type_pkgs = [
                     ('bigReg', 'skip: True  # [not unix]'),
                     ('blatr', 'skip: True  # [not win]')
                    ]


@pytest.mark.parametrize("package, skip_text", cran_os_type_pkgs)
def test_cran_os_type(package, skip_text, testing_workdir, testing_config):
    api.skeletonize(packages=package, repo='cran', output_dir=testing_workdir,
                    config=testing_config)
    fpath = os.path.join(testing_workdir, 'r-' + package.lower(), 'meta.yaml')
    with open(fpath) as f:
        assert skip_text in f.read()


# Test cran skeleton argument --no-comments
def test_cran_no_comments(testing_workdir, testing_config):
    package = "data.table"
    meta_yaml_comment = '  # This is required to make R link correctly on Linux.'
    build_sh_comment = '# Add more build steps here, if they are necessary.'
    build_sh_shebang = '#!/bin/bash'

    # Check that comments are part of the templates
    assert meta_yaml_comment in CRAN_META
    assert build_sh_comment in CRAN_BUILD_SH_SOURCE
    assert build_sh_shebang in CRAN_BUILD_SH_SOURCE

    api.skeletonize(packages=package, repo='cran', output_dir=testing_workdir,
                    config=testing_config, no_comments=True)

    # Check that comments got removed
    meta_yaml = os.path.join(testing_workdir, 'r-' + package.lower(), 'meta.yaml')
    with open(meta_yaml) as f:
        assert meta_yaml_comment not in f.read()

    build_sh = os.path.join(testing_workdir, 'r-' + package.lower(), 'build.sh')
    with open(build_sh) as f:
        build_sh_text = f.read()
        assert build_sh_comment not in build_sh_text
        assert build_sh_shebang in build_sh_text
