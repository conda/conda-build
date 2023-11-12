# Copyright (C) 2012 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""(Legacy) Low-level implementation of a Channel."""
import re
from typing import NamedTuple

from .conda_imports import (
    CONDA_PACKAGE_EXTENSIONS,
    UNKNOWN_CHANNEL,
    CondaError,
    Channel,
    Entity,
    EntityType,
    IntegerField,
    PackageRecord,
    StringField,
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


class DistType(EntityType):
    def _make_dist(cls, value):
        if isinstance(value, Dist):
            return dist
        if isinstance(value, PackageRecord):
            dist_kwargs = _as_dict_from_string(
                value.fn, channel_override=value.channel.canonical_name
            )
            return super().__call__(**dist_kwargs)
        if isinstance(value, str):
            dist_kwargs = _as_dict_from_string(value)
            return super().__call__(**dist_kwargs)
        raise NotImplementedError()

    def __call__(cls, value):
        if value in Dist._cache_:
            return Dist._cache_[value]
        dist = cls._make_dist(value)
        Dist._cache_[value] = dist
        return dist


class Dist(Entity, metaclass=DistType):
    _cache_ = {}
    _lazy_validate = True

    channel = StringField(required=False, nullable=True, immutable=True)

    dist_name = StringField(immutable=True)
    name = StringField(immutable=True)
    fmt = StringField(immutable=True)
    version = StringField(immutable=True)
    build = StringField(immutable=True)
    build_number = IntegerField(immutable=True)

    base_url = StringField(required=False, nullable=True, immutable=True)
    subdir = StringField(required=False, nullable=True, immutable=True)

    def __init__(
        self,
        channel,
        dist_name=None,
        name=None,
        version=None,
        build=None,
        build_number=None,
        base_url=None,
        subdir=None,
        fmt=".tar.bz2",
    ):
        super().__init__(
            channel=channel,
            dist_name=dist_name,
            name=name,
            version=version,
            build=build,
            build_number=build_number,
            base_url=base_url,
            subdir=subdir,
            fmt=fmt,
        )

    def to_package_ref(self):
        return PackageRecord(
            channel=self.channel,
            subdir=self.subdir,
            name=self.name,
            version=self.version,
            build=self.build,
            build_number=self.build_number,
        )

    def __str__(self):
        raise NotImplementedError()

    def __key__(self):
        return self.channel, self.dist_name

    def __lt__(self, other):
        raise NotImplementedError()
        return self.__key__() < other.__key__()

    def __gt__(self, other):
        raise NotImplementedError()
        return self.__key__() > other.__key__()

    def __le__(self, other):
        raise NotImplementedError()
        return self.__key__() <= other.__key__()

    def __ge__(self, other):
        raise NotImplementedError()
        return self.__key__() >= other.__key__()

    def __hash__(self):
        # dists compare equal regardless of fmt, but fmt is taken into account for
        #    object identity
        return hash((self.__key__(), self.fmt))

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.__key__() == other.__key__()

    def __ne__(self, other):
        return not self.__eq__(other)

    # ############ conda-build compatibility ################

    def split(self, sep=None, maxsplit=-1):
        raise NotImplementedError()

    def rsplit(self, sep=None, maxsplit=-1):
        raise NotImplementedError()

    def __contains__(self, item):
        def to_str(x):
            return f"{x.channel}::{x.dist_name}" if x.channel else x.dist_name

        if isinstance(item, Dist):
            item = to_str(item)
        item = _strip_extension(item)
        return item in to_str(self)

    @property
    def fn(self):
        raise NotImplementedError()
