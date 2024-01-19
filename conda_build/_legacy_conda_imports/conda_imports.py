try:
    from boltons.setutils import IndexedSet
except ImportError:  # pragma: no cover
    from conda._vendor.boltons.setutils import IndexedSet

from conda.exports import (
    Channel,
    MatchSpec,
    PackageRecord,
    ProgressiveFetchExtract,
    on_win,
)

from conda.base.constants import (
    DEFAULTS_CHANNEL_NAME,
    UNKNOWN_CHANNEL,
)
from conda.base.context import context, stack_context_default
from conda.common.io import env_vars
from conda.core.index import LAST_CHANNEL_URLS, get_index
from conda.core.link import PrefixSetup, UnlinkLinkTransaction
from conda.core.prefix_data import PrefixData
from conda.models.channel import prioritize_channels
