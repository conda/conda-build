from .conda_imports import get_index as _get_index
from .instructions import (
    LINK,
    PREFIX,
)
from .plan import (
    display_actions
    execute_actions,
    install_actions,
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
    return _get_index(
        channel_urls, prepend, platform, use_local, use_cache, unknown, prefix
    )
