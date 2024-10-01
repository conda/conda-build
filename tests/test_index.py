# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from typing import TYPE_CHECKING

from conda.base.context import context

from conda_build.index import get_build_index

if TYPE_CHECKING:
    from conda_build.metadata import MetaData


def test_get_build_index(testing_metadata: MetaData, benchmark) -> None:
    @benchmark
    def _():
        get_build_index(
            subdir=context.subdir,
            bldpkgs_dir=testing_metadata.config.bldpkgs_dir,
            output_folder=testing_metadata.config.output_folder,
            clear_cache=True,
            omit_defaults=True,
            channel_urls=["local", "conda-forge", "defaults"],
        )
