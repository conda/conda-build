# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
# This is just here so that tests is a package, so that dotted relative
# imports work.

from pathlib import Path

TESTS_PATH = Path(__file__).parent
"Test suite root directory."

LOCAL_CHANNEL_PATH = TESTS_PATH / "local-channel"
"Local channel."

METADATA_V2_PATH = TESTS_PATH / "test-recipes" / "metadata-v2"
"Test recipes using the local channel."
