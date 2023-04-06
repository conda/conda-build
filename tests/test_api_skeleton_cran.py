# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
Integrative tests of the CRAN skeleton that start from
conda_build.api.skeletonize and check the output files
"""
from pathlib import Path
from typing import Sequence

import pytest

from conda_build import api
from conda_build.skeletons.cran import CRAN_BUILD_SH_SOURCE, CRAN_META


@pytest.mark.skip("Use separate grayskull package instead of skeleton.")
@pytest.mark.slow
@pytest.mark.parametrize(
    "package,license_id,license_family,license_files",
    [
        ("r-rmarkdown", "GPL-3", "GPL3", {"GPL-3"}),
        ("r-fastdigest", "Artistic-2.0", "OTHER", {"Artistic-2.0"}),
        ("r-tokenizers.bpe", "MPL-2.0", "OTHER", set()),
        ("r-broom", "MIT", "MIT", {"MIT", "LICENSE"}),
        ("r-meanr", "BSD_2_clause", "BSD", {"BSD_2_clause", "LICENSE"}),
        ("r-base64enc", "GPL-2 | GPL-3", "GPL3", {"GPL-2", "GPL-3"}),
        ("r-magree", "GPL-3 | GPL-2", "GPL3", {"GPL-3", "GPL-2"}),
        ("r-mglm", "GPL-2", "GPL2", {"GPL-2"}),
    ],
)
# @pytest.mark.flaky(rerun=5, reruns_delay=2)
def test_cran_license(
    package: str,
    license_id: str,
    license_family: str,
    license_files: Sequence[str],
    tmp_path: Path,
    testing_config,
):
    api.skeletonize(
        packages=package, repo="cran", output_dir=tmp_path, config=testing_config
    )
    m = api.render(str(tmp_path / package / "meta.yaml"))[0][0]

    assert m.get_value("about/license") == license_id
    assert m.get_value("about/license_family") == license_family
    assert {
        Path(license).name for license in m.get_value("about/license_file", "")
    } == set(license_files)


@pytest.mark.skip("Use separate grayskull package instead of skeleton.")
@pytest.mark.parametrize(
    "package,skip_text",
    [
        ("bigReg", "skip: True  # [not unix]"),
        ("blatr", "skip: True  # [not win]"),
    ],
)
@pytest.mark.flaky(rerun=5, reruns_delay=2)
def test_cran_os_type(package: str, skip_text: str, tmp_path: Path, testing_config):
    api.skeletonize(
        packages=package, repo="cran", output_dir=tmp_path, config=testing_config
    )
    assert skip_text in (tmp_path / f"r-{package.lower()}" / "meta.yaml").read_text()


# Test cran skeleton argument --no-comments
@pytest.mark.flaky(rerun=5, reruns_delay=2)
def test_cran_no_comments(tmp_path: Path, testing_config):
    package = "data.table"
    meta_yaml_comment = "  # This is required to make R link correctly on Linux."
    build_sh_comment = "# Add more build steps here, if they are necessary."
    build_sh_shebang = "#!/bin/bash"

    # Check that comments are part of the templates
    assert meta_yaml_comment in CRAN_META
    assert build_sh_comment in CRAN_BUILD_SH_SOURCE
    assert build_sh_shebang in CRAN_BUILD_SH_SOURCE

    api.skeletonize(
        packages=package,
        repo="cran",
        output_dir=tmp_path,
        config=testing_config,
        no_comments=True,
    )

    # Check that comments got removed
    meta_yaml_text = (tmp_path / f"r-{package.lower()}" / "meta.yaml").read_text()
    assert meta_yaml_comment not in meta_yaml_text

    build_sh_text = (tmp_path / f"r-{package.lower()}" / "build.sh").read_text()
    assert build_sh_comment not in build_sh_text
    assert build_sh_shebang in build_sh_text
