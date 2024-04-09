# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import os
import os.path
import sys
from logging import INFO, WARNING, Filter, Formatter, StreamHandler, getLogger
from logging.config import dictConfig
from pathlib import Path
from typing import TYPE_CHECKING

from conda.base.context import context
from yaml import safe_load

if TYPE_CHECKING:
    from logging import Logger, LogRecord
    from typing import Self


# https://stackoverflow.com/a/31459386/1170370
class LessThanFilter(Filter):
    def __init__(self, exclusive_maximum: int, name: str = "") -> None:
        super().__init__(name)
        self.max_level = exclusive_maximum

    def filter(self, record: LogRecord) -> bool:
        return record.levelno < self.max_level


class GreaterThanFilter(Filter):
    def __init__(self, exclusive_minimum: int, name: str = "") -> None:
        super().__init__(name)
        self.min_level = exclusive_minimum

    def filter(self, record: LogRecord) -> bool:
        return record.levelno > self.min_level


class DuplicateFilter(Filter):
    msgs: set[str] = set()

    def filter(self, record: LogRecord) -> bool:
        try:
            return record.msg not in self.msgs
        finally:
            self.msgs.add(record.msg)

    @classmethod
    def clear(cls: type[Self]) -> None:
        cls.msgs.clear()


def init_logging(log: Logger) -> None:
    """
    Default initialization of logging for conda-build CLI.

    When using conda-build as a CLI tool (not as a library) we wish to limit logging to
    avoid duplication and to otherwise offer some default behavior.
    """
    config_file = context.conda_build.get("log_config_file")
    if config_file:
        config_file = os.path.expandvars(config_file)
        dictConfig(safe_load(Path(config_file).expanduser().resolve().read_text()))

    # we don't want propagation in CLI, but we do want it in tests
    # this is a pytest limitation: https://github.com/pytest-dev/pytest/issues/3697
    getLogger("conda_build").propagate = "PYTEST_CURRENT_TEST" in os.environ

    if not log.handlers:
        log.addHandler(stdout := StreamHandler(sys.stdout))
        stdout.addFilter(LessThanFilter(WARNING))
        stdout.addFilter(DuplicateFilter())
        stdout.setFormatter(Formatter("%(levelname)s: %(message)s"))

        log.addHandler(stderr := StreamHandler(sys.stderr))
        stderr.addFilter(GreaterThanFilter(INFO))
        stderr.addFilter(DuplicateFilter())
        stderr.setFormatter(Formatter("%(levelname)s: %(message)s"))
