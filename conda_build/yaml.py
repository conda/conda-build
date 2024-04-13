# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, overload

from frozendict import frozendict
from yaml import dump as _dump
from yaml import load as _load
from yaml.error import YAMLError  # noqa: F401

try:
    from yaml import CSafeDumper as _SafeDumper
    from yaml import CSafeLoader as _SafeLoader
except ImportError:
    from yaml import SafeDumper as _SafeDumper  # type: ignore[assignment]
    from yaml import SafeLoader as _SafeLoader  # type: ignore[assignment]

if TYPE_CHECKING:
    from typing import Any, Self, TextIO


class _NoAliasesDumper(_SafeDumper):
    def ignore_aliases(self: Self, data: Any) -> bool:
        return True


_NoAliasesDumper.add_representer(set, _NoAliasesDumper.represent_list)
_NoAliasesDumper.add_representer(tuple, _NoAliasesDumper.represent_list)
_NoAliasesDumper.add_representer(OrderedDict, _NoAliasesDumper.represent_dict)
_NoAliasesDumper.add_representer(frozendict, _NoAliasesDumper.represent_dict)


@overload
def safe_dump(data: Any, stream: None = None, **kwargs) -> str: ...


@overload
def safe_dump(data: Any, stream: TextIO, **kwargs) -> None: ...


def safe_dump(
    data: Any,
    stream: TextIO | None = None,
    *,
    default_flow_style: bool = False,  # always serialize in the block style
    indent: int = 2,
    sort_keys: bool = False,  # prefer the manual ordering
    **kwargs,
) -> str | None:
    return _dump(
        data,
        stream,
        Dumper=_NoAliasesDumper,
        default_flow_style=default_flow_style,
        indent=indent,
        **kwargs,
    )


class _StringifyNumbersLoader(_SafeLoader):
    @classmethod
    def remove_implicit_resolver(cls, tag):
        if "yaml_implicit_resolvers" not in cls.__dict__:
            cls.yaml_implicit_resolvers = {
                k: v[:] for k, v in cls.yaml_implicit_resolvers.items()
            }
        for ch in tuple(cls.yaml_implicit_resolvers):
            resolvers = [(t, r) for t, r in cls.yaml_implicit_resolvers[ch] if t != tag]
            if resolvers:
                cls.yaml_implicit_resolvers[ch] = resolvers
            else:
                del cls.yaml_implicit_resolvers[ch]

    @classmethod
    def remove_constructor(cls, tag):
        if "yaml_constructors" not in cls.__dict__:
            cls.yaml_constructors = cls.yaml_constructors.copy()
        if tag in cls.yaml_constructors:
            del cls.yaml_constructors[tag]


_StringifyNumbersLoader.remove_implicit_resolver("tag:yaml.org,2002:float")
_StringifyNumbersLoader.remove_implicit_resolver("tag:yaml.org,2002:int")
_StringifyNumbersLoader.remove_constructor("tag:yaml.org,2002:float")
_StringifyNumbersLoader.remove_constructor("tag:yaml.org,2002:int")


def safe_load(stream: str | TextIO, *, stringify_numbers: bool = False) -> Any:
    return _load(
        stream,
        _StringifyNumbersLoader if stringify_numbers else _SafeLoader,
    )
