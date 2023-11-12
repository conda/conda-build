# Copyright (C) 2012 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""(Legacy) Low-level implementation of a Channel."""
import re
from typing import NamedTuple

from .conda_imports import (
    CONDA_PACKAGE_EXTENSIONS,
    DEFAULTS_CHANNEL_NAME,
    NULL,
    UNKNOWN_CHANNEL,
    CondaError,
    Channel,
    Entity,
    EntityType,
    IntegerField,
    MatchSpec,
    PackageInfo,
    PackageRecord,
    StringField,
    context,
    ensure_text_type,
    has_platform,
    is_url,
    join_url,
)


class DistDetails(NamedTuple):
    name: str
    version: str
    build_string: str
    build_number: str
    dist_name: str
    fmt: str


class DistType(EntityType):
    def __call__(cls, value):
        if value in Dist._cache_:
            return Dist._cache_[value]
        elif isinstance(value, Dist):
            dist = value
        elif isinstance(value, PackageRecord):
            dist_kwargs = Dist._as_dict_from_string(
                value.fn, channel_override=value.channel.canonical_name
            )
            dist = super().__call__(**dist_kwargs)
        elif hasattr(value, "dist") and isinstance(value.dist, Dist):
            raise NotImplementedError()
        elif isinstance(value, PackageInfo):
            dist_kwargs = Dist._as_dict_from_string(
                value.repodata_record.fn,
                channel_override=value.channel.canonical_name,
            )
            dist = super().__call__(**dist_kwargs)
        elif isinstance(value, Channel):
            raise NotImplementedError()
        else:
            dist_kwargs = Dist._as_dict_from_string(value)
            dist = super().__call__(**dist_kwargs)
        Dist._cache_[value] = dist
        return dist


def strip_extension(original_dist):
    for ext in CONDA_PACKAGE_EXTENSIONS:
        if original_dist.endswith(ext):
            original_dist = original_dist[: -len(ext)]
    return original_dist


def split_extension(original_dist):
    stripped = strip_extension(original_dist)
    return stripped, original_dist[len(stripped) :]


class Dist(Entity, metaclass=DistType):
    _cache_ = {}
    _lazy_validate = True

    channel = StringField(required=False, nullable=True, immutable=True)

    dist_name = StringField(immutable=True)
    name = StringField(immutable=True)
    fmt = StringField(immutable=True)
    version = StringField(immutable=True)
    build_string = StringField(immutable=True)
    build_number = IntegerField(immutable=True)

    base_url = StringField(required=False, nullable=True, immutable=True)
    platform = StringField(required=False, nullable=True, immutable=True)

    def __init__(
        self,
        channel,
        dist_name=None,
        name=None,
        version=None,
        build_string=None,
        build_number=None,
        base_url=None,
        platform=None,
        fmt=".tar.bz2",
    ):
        super().__init__(
            channel=channel,
            dist_name=dist_name,
            name=name,
            version=version,
            build_string=build_string,
            build_number=build_number,
            base_url=base_url,
            platform=platform,
            fmt=fmt,
        )

    def to_package_ref(self):
        return PackageRecord(
            channel=self.channel,
            subdir=self.platform,
            name=self.name,
            version=self.version,
            build=self.build_string,
            build_number=self.build_number,
        )

    @property
    def build(self):
        return self.build_string

    @property
    def subdir(self):
        return self.platform

    @property
    def quad(self):
        # returns: name, version, build_string, channel
        parts = self.dist_name.rsplit("-", 2) + ["", ""]
        return parts[0], parts[1], parts[2], self.channel or DEFAULTS_CHANNEL_NAME

    def __str__(self):
        return f"{self.channel}::{self.dist_name}" if self.channel else self.dist_name

    @classmethod
    def _as_dict_from_string(cls, string, channel_override=NULL):
        string = str(string)

        if is_url(string) and channel_override == NULL:
            return cls._as_dict_from_url(string)

        if string.endswith("@"):
            return dict(
                channel="@",
                name=string,
                version="",
                build_string="",
                build_number=0,
                dist_name=string,
            )

        REGEX_STR = (
            r"(?:([^\s\[\]]+)::)?"  # optional channel
            r"([^\s\[\]]+)"  # 3.x dist
            r"(?:\[([a-zA-Z0-9_-]+)\])?"  # with_features_depends
        )
        channel, original_dist, w_f_d = re.search(REGEX_STR, string).groups()

        original_dist, fmt = split_extension(original_dist)

        if channel_override != NULL:
            channel = channel_override
        if not channel:
            channel = UNKNOWN_CHANNEL

        # enforce dist format
        dist_details = cls.parse_dist_name(original_dist)
        return dict(
            channel=channel,
            name=dist_details.name,
            version=dist_details.version,
            build_string=dist_details.build_string,
            build_number=dist_details.build_number,
            dist_name=original_dist,
            fmt=fmt,
        )

    @staticmethod
    def parse_dist_name(string):
        original_string = string
        try:
            string = ensure_text_type(string)
            no_fmt_string, fmt = split_extension(string)

            # remove any directory or channel information
            if "::" in no_fmt_string:
                dist_name = no_fmt_string.rsplit("::", 1)[-1]
            else:
                dist_name = no_fmt_string.rsplit("/", 1)[-1]

            parts = dist_name.rsplit("-", 2)

            name = parts[0]
            version = parts[1]
            build_string = parts[2] if len(parts) >= 3 else ""
            build_number_as_string = "".join(
                filter(
                    lambda x: x.isdigit(),
                    (build_string.rsplit("_")[-1] if build_string else "0"),
                )
            )
            build_number = int(build_number_as_string) if build_number_as_string else 0

            return DistDetails(
                name, version, build_string, build_number, dist_name, fmt
            )

        except:
            raise CondaError(
                "dist_name is not a valid conda package: %s" % original_string
            )

    @classmethod
    def _as_dict_from_url(cls, url):
        assert is_url(url), url
        if (
            not any(url.endswith(ext) for ext in CONDA_PACKAGE_EXTENSIONS)
            and "::" not in url
        ):
            raise CondaError("url '%s' is not a conda package" % url)

        dist_details = cls.parse_dist_name(url)
        if "::" in url:
            url_no_tarball = url.rsplit("::", 1)[0]
            platform = context.subdir
            base_url = url_no_tarball.split("::")[0]
            channel = str(Channel(base_url))
        else:
            url_no_tarball = url.rsplit("/", 1)[0]
            platform = has_platform(url_no_tarball, context.known_subdirs)
            base_url = url_no_tarball.rsplit("/", 1)[0] if platform else url_no_tarball
            channel = Channel(base_url).canonical_name if platform else UNKNOWN_CHANNEL

        return dict(
            channel=channel,
            name=dist_details.name,
            version=dist_details.version,
            build_string=dist_details.build_string,
            build_number=dist_details.build_number,
            dist_name=dist_details.dist_name,
            base_url=base_url,
            platform=platform,
            fmt=dist_details.fmt,
        )

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
        assert sep == "::"
        return [self.channel, self.dist_name] if self.channel else [self.dist_name]

    def rsplit(self, sep=None, maxsplit=-1):
        assert sep == "-"
        assert maxsplit == 2
        name = f"{self.channel}::{self.quad[0]}" if self.channel else self.quad[0]
        return name, self.quad[1], self.quad[2]

    def __contains__(self, item):
        item = strip_extension(ensure_text_type(item))
        return item in self.__str__()

    @property
    def fn(self):
        return self.to_package_ref().fn
