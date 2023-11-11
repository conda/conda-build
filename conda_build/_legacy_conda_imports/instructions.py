# Copyright (C) 2012 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""Define the instruction set (constants) for conda operations."""
from logging import getLogger

from conda.core.link import UnlinkLinkTransaction
from conda.core.package_cache_data import ProgressiveFetchExtract

log = getLogger(__name__)

# op codes
CHECK_FETCH = "CHECK_FETCH"
FETCH = "FETCH"
CHECK_EXTRACT = "CHECK_EXTRACT"
EXTRACT = "EXTRACT"
RM_EXTRACTED = "RM_EXTRACTED"
RM_FETCHED = "RM_FETCHED"
PREFIX = "PREFIX"
PRINT = "PRINT"
PROGRESS = "PROGRESS"
SYMLINK_CONDA = "SYMLINK_CONDA"
UNLINK = "UNLINK"
LINK = "LINK"
UNLINKLINKTRANSACTION = "UNLINKLINKTRANSACTION"
PROGRESSIVEFETCHEXTRACT = "PROGRESSIVEFETCHEXTRACT"


PROGRESS_COMMANDS = {EXTRACT, RM_EXTRACTED}
ACTION_CODES = (
    CHECK_FETCH,
    FETCH,
    CHECK_EXTRACT,
    EXTRACT,
    UNLINK,
    LINK,
    SYMLINK_CONDA,
    RM_EXTRACTED,
    RM_FETCHED,
)


def PREFIX_CMD(state, prefix):
    state["prefix"] = prefix


def PRINT_CMD(state, arg):  # pragma: no cover
    if arg.startswith(("Unlinking packages", "Linking packages")):
        return
    getLogger("conda.stdout.verbose").info(arg)


def FETCH_CMD(state, package_cache_entry):
    raise NotImplementedError()


def EXTRACT_CMD(state, arg):
    raise NotImplementedError()


def PROGRESSIVEFETCHEXTRACT_CMD(state, progressive_fetch_extract):  # pragma: no cover
    assert isinstance(progressive_fetch_extract, ProgressiveFetchExtract)
    progressive_fetch_extract.execute()


def UNLINKLINKTRANSACTION_CMD(state, arg):  # pragma: no cover
    unlink_link_transaction = arg
    assert isinstance(unlink_link_transaction, UnlinkLinkTransaction)
    unlink_link_transaction.execute()


# Map instruction to command (a python function)
commands = {
    PREFIX: PREFIX_CMD,
    PRINT: PRINT_CMD,
    FETCH: FETCH_CMD,
    PROGRESS: lambda x, y: None,
    EXTRACT: EXTRACT_CMD,
    RM_EXTRACTED: lambda x, y: None,
    RM_FETCHED: lambda x, y: None,
    UNLINK: None,
    LINK: None,
    SYMLINK_CONDA: lambda x, y: None,
    UNLINKLINKTRANSACTION: UNLINKLINKTRANSACTION_CMD,
    PROGRESSIVEFETCHEXTRACT: PROGRESSIVEFETCHEXTRACT_CMD,
}


OP_ORDER = (
    RM_FETCHED,
    FETCH,
    RM_EXTRACTED,
    EXTRACT,
    UNLINK,
    LINK,
)
