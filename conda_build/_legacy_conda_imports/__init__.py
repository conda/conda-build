from conda.core.index import get_index as _get_index
from conda.core.package_cache_data import PackageCacheData
from conda.core.prefix_data import PrefixData
from conda.models.enums import PackageType
from conda.instructions import (
    EXTRACT,
    FETCH,
    LINK,
    PREFIX,
    RM_EXTRACTED,
    RM_FETCHED,
    UNLINK,
)

from .dist import Dist
from .plan import (
    display_actions as _display_actions,
    execute_actions,
    execute_plan,
    install_actions,
)


def display_actions(
    actions, index, show_channel_urls=None, specs_to_remove=(), specs_to_add=()
):
    if FETCH in actions:
        actions[FETCH] = [index[d] for d in actions[FETCH]]
    if LINK in actions:
        actions[LINK] = [index[d] for d in actions[LINK]]
    if UNLINK in actions:
        actions[UNLINK] = [index[d] for d in actions[UNLINK]]
    index = {prec: prec for prec in index.values()}
    return _display_actions(
        actions, index, show_channel_urls, specs_to_remove, specs_to_add
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


def package_cache():
    class package_cache:
        def __contains__(self, dist):
            return bool(
                PackageCacheData.first_writable().get(Dist(dist).to_package_ref(), None)
            )

        def keys(self):
            return (Dist(v) for v in PackageCacheData.first_writable().values())

        def __delitem__(self, dist):
            PackageCacheData.first_writable().remove(Dist(dist).to_package_ref())

    return package_cache()


def linked_data(prefix, ignore_channels=False):
    """Return a dictionary of the linked packages in prefix."""
    pd = PrefixData(prefix)
    return {
        Dist(prefix_record): prefix_record
        for prefix_record in pd._prefix_records.values()
    }


def linked(prefix, ignore_channels=False):
    """Return the Dists of linked packages in prefix."""
    conda_package_types = PackageType.conda_package_types()
    ld = linked_data(prefix, ignore_channels=ignore_channels).items()
    return {
        dist
        for dist, prefix_rec in ld
        if prefix_rec.package_type in conda_package_types
    }
