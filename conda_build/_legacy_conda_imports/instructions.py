# Copyright (C) 2012 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""Define the instruction set (constants) for conda operations."""
from logging import getLogger

from .conda_imports import ProgressiveFetchExtract, UnlinkLinkTransaction

log = getLogger(__name__)

# op codes
PREFIX = "PREFIX"
LINK = "LINK"
UNLINKLINKTRANSACTION = "UNLINKLINKTRANSACTION"
PROGRESSIVEFETCHEXTRACT = "PROGRESSIVEFETCHEXTRACT"


def PREFIX_CMD(prefix):
    pass


def PROGRESSIVEFETCHEXTRACT_CMD(progressive_fetch_extract):  # pragma: no cover
    assert isinstance(progressive_fetch_extract, ProgressiveFetchExtract)
    progressive_fetch_extract.execute()


def UNLINKLINKTRANSACTION_CMD(arg):  # pragma: no cover
    unlink_link_transaction = arg
    assert isinstance(unlink_link_transaction, UnlinkLinkTransaction)
    unlink_link_transaction.execute()


# Map instruction to command (a python function)
commands = {
    PREFIX: PREFIX_CMD,
    LINK: None,
    UNLINKLINKTRANSACTION: UNLINKLINKTRANSACTION_CMD,
    PROGRESSIVEFETCHEXTRACT: PROGRESSIVEFETCHEXTRACT_CMD,
}
