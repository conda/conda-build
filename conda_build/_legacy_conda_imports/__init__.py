from .conda_imports import (
    PackageType as _PackageType,
    PrefixData as _PrefixData,
    get_index as _get_index,
)
from .dist import Dist
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
    return {Dist(prec): prec for prec in index.values()}
