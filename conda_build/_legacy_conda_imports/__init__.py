from .conda_imports import get_index as _get_index
from .instructions import (
    LINK,
    PREFIX,
)
from .plan import (
    display_actions as _display_actions,
    execute_actions,
    install_actions,
)


def display_actions(
    actions, index, show_channel_urls=None, specs_to_remove=(), specs_to_add=()
):
    if LINK in actions:
        actions[LINK] = [index[d] for d in actions[LINK]]
    return _display_actions(
        actions, show_channel_urls, specs_to_remove, specs_to_add
    )


class _TemporaryIndexWrapper:
    def __init__(self, index):
        self._internal_index = index
        self._internal_dict = {prec: prec for prec in index.values()}
    def __contains__(self, key):
        raise NotImplementedError()
    def __iter__(self):
        return self._internal_dict.__iter__()
    def get(self, key, fallback=None):
        raise NotImplementedError()
    def __getitem__(self, key):
        ret = self._internal_dict.__getitem__(key)
        return ret
    def get_internal_index(self):
        return self._internal_index


def get_index(
    channel_urls=(),
    prepend=True,
    platform=None,
    use_local=False,
    use_cache=False,
    unknown=None,
    prefix=None,
):
    index = _get_index(
        channel_urls, prepend, platform, use_local, use_cache, unknown, prefix
    )
    return _TemporaryIndexWrapper(index)
