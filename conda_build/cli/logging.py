# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import logging
import logging.config
import os
import os.path
import sys
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from conda.base.context import context
from yaml import safe_load

if TYPE_CHECKING:
    from logging import LogRecord


# https://stackoverflow.com/a/31459386/1170370
class LessThanFilter(logging.Filter):
    def __init__(self, exclusive_maximum: int, name: str = "") -> None:
        super().__init__(name)
        self.max_level = exclusive_maximum

    def filter(self, record: LogRecord) -> bool:
        return record.levelno < self.max_level


class GreaterThanFilter(logging.Filter):
    def __init__(self, exclusive_minimum: int, name: str = "") -> None:
        super().__init__(name)
        self.min_level = exclusive_minimum

    def filter(self, record: LogRecord) -> bool:
        return record.levelno > self.min_level


class DuplicateFilter(logging.Filter):
    msgs: set[str] = set()

    def filter(self, record: LogRecord) -> bool:
        try:
            return record.msg not in self.msgs
        finally:
            self.msgs.add(record.msg)


@lru_cache
def init_logging() -> None:
    """
    Default initialization of logging for conda-build CLI.

    When using conda-build as a CLI tool (not as a library) we wish to limit logging to
    avoid duplication and to otherwise offer some default behavior.

    This is a onetime initialization that should be called at the start of CLI execution.
    """
    # undo conda messing with the root logger
    logging.getLogger(None).setLevel(logging.WARNING)

    # load the logging configuration from the config file
    config_file = context.conda_build.get("log_config_file")
    if config_file:
        config_file = Path(os.path.expandvars(config_file)).expanduser().resolve()
        logging.config.dictConfig(safe_load(config_file.read_text()))

    log = logging.getLogger("conda_build")

    # historically conda_build has defaulted the logging to INFO and so all of the
    # log.info is viewed as default output, until we convert all of the existing
    # log.info to standard print statements we will need to continue defaulting to INFO
    if log.level == logging.NOTSET:
        log.setLevel(logging.INFO)

    # we don't want propagation to the root logger in CLI, but we do want it in tests
    # this is a pytest limitation: https://github.com/pytest-dev/pytest/issues/3697
    log.propagate = "PYTEST_CURRENT_TEST" in os.environ

    if not log.handlers:
        # only add our handlers when none are added via logging.config

        # filter DEBUG/INFO messages to stdout
        log.addHandler(stdout := logging.StreamHandler(sys.stdout))
        stdout.addFilter(LessThanFilter(logging.WARNING))
        stdout.addFilter(DuplicateFilter())  # avoid duplicate messages
        stdout.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

        # filter WARNING/ERROR/CRITICAL messages to stderr
        log.addHandler(stderr := logging.StreamHandler(sys.stderr))
        stderr.addFilter(GreaterThanFilter(logging.INFO))
        stderr.addFilter(DuplicateFilter())  # avoid duplicate messages
        stderr.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
