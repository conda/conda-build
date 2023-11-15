# Copyright (C) 2012 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""(Legacy) Low-level implementation of a Channel."""
import re
from typing import NamedTuple

from .conda_imports import (
    CONDA_PACKAGE_EXTENSIONS,
    UNKNOWN_CHANNEL,
    CondaError,
    PackageRecord,
    is_url,
)


class DistDetails(NamedTuple):
    name: str
    version: str
    build: str
    build_number: str
    dist_name: str
    fmt: str


def _strip_extension(original_dist):
    for ext in CONDA_PACKAGE_EXTENSIONS:
        if original_dist.endswith(ext):
            original_dist = original_dist[: -len(ext)]
    return original_dist


def _split_extension(original_dist):
    stripped = _strip_extension(original_dist)
    return stripped, original_dist[len(stripped) :]


def _parse_dist_name(string):
    original_string = string
    try:
        no_fmt_string, fmt = _split_extension(string)

        # remove any directory or channel information
        if "::" in no_fmt_string:
            dist_name = no_fmt_string.rsplit("::", 1)[-1]
        else:
            dist_name = no_fmt_string.rsplit("/", 1)[-1]

        parts = dist_name.rsplit("-", 2)

        name = parts[0]
        version = parts[1]
        build = parts[2] if len(parts) >= 3 else ""
        build_number_as_string = "".join(
            filter(
                lambda x: x.isdigit(),
                (build.rsplit("_")[-1] if build else "0"),
            )
        )
        build_number = int(build_number_as_string) if build_number_as_string else 0

        return DistDetails(
            name, version, build, build_number, dist_name, fmt
        )

    except:
        raise CondaError(
            "dist_name is not a valid conda package: %s" % original_string
        )


_not_set = object()


def _as_dict_from_string(string, channel_override=_not_set):
    if is_url(string) and channel_override == _not_set:
        raise NotImplementedError()

    if string.endswith("@"):
        raise NotImplementedError()

    REGEX_STR = (
        r"(?:([^\s\[\]]+)::)?"  # optional channel
        r"([^\s\[\]]+)"  # 3.x dist
        r"(?:\[([a-zA-Z0-9_-]+)\])?"  # with_features_depends
    )
    channel, original_dist, w_f_d = re.search(REGEX_STR, string).groups()

    original_dist, fmt = _split_extension(original_dist)

    if channel_override != _not_set:
        channel = channel_override
    if not channel:
        channel = UNKNOWN_CHANNEL

    # enforce dist format
    dist_details = _parse_dist_name(original_dist)
    return dict(
        channel=channel,
        name=dist_details.name,
        version=dist_details.version,
        build=dist_details.build,
        build_number=dist_details.build_number,
        dist_name=original_dist,
        fmt=fmt,
    )


def package_ref_from_dist_string(dist_string):
    dist_kwargs = _as_dict_from_string(dist_string)
    return PackageRecord(
        channel=dist_kwargs["channel"],
        name=dist_kwargs["name"],
        version=dist_kwargs["version"],
        build=dist_kwargs["build"],
        build_number=dist_kwargs["build_number"],
    )


def dist_string_contains(containing_dist_string, contained_dist_string):
    contained_dist_string = _strip_extension(contained_dist_string)
    return contained_dist_string in containing_dist_string


def dist_string_from_package_record(package_record, channel=None):
    if channel is None:
        channel = package_record.channel.canonical_name
    dist_kwargs = _as_dict_from_string(
        package_record.fn, channel_override=channel
    )
    channel = dist_kwargs["channel"]
    dist_name = dist_kwargs["dist_name"]
    return f"{channel}::{dist_name}" if channel else dist_name
