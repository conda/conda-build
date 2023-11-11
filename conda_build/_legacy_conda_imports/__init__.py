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


def linked_data(prefix, ignore_channels=False):
    """Return a dictionary of the linked packages in prefix."""
    pd = _PrefixData(prefix)
    return {
        Dist(prefix_record): prefix_record
        for prefix_record in pd._prefix_records.values()
    }


def linked(prefix, ignore_channels=False):
    """Return the Dists of linked packages in prefix."""
    conda_package_types = _PackageType.conda_package_types()
    ld = linked_data(prefix, ignore_channels=ignore_channels).items()
    return {
        dist
        for dist, prefix_rec in ld
        if prefix_rec.package_type in conda_package_types
    }
