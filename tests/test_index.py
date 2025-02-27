# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from conda.base.context import context

from conda_build.index import get_build_index

if TYPE_CHECKING:
    from conda_build.metadata import MetaData


@pytest.mark.benchmark
def test_get_build_index(testing_metadata: MetaData) -> None:
    get_build_index(
        subdir=context.subdir,
        bldpkgs_dir=testing_metadata.config.bldpkgs_dir,
        output_folder=testing_metadata.config.output_folder,
        clear_cache=True,
        omit_defaults=True,
        channel_urls=["local", "conda-forge", "defaults"],
    )
