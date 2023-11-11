try:
    from boltons.setutils import IndexedSet
except ImportError:  # pragma: no cover
    from conda._vendor.boltons.setutils import IndexedSet

from conda.exports import (
    Channel,
    CondaError,
    MatchSpec,
    PackageRecord,
    ProgressiveFetchExtract,
    context,
    on_win,
    normalized_version,
)

from conda.auxlib.entity import Entity, EntityType, IntegerField, StringField
from conda.base.constants import (
    CONDA_PACKAGE_EXTENSIONS,
    DEFAULTS_CHANNEL_NAME,
    UNKNOWN_CHANNEL,
)
from conda.base.context import stack_context_default
from conda.common.compat import ensure_text_type
from conda.common.constants import NULL
from conda.common.io import dashlist, env_vars
from conda.common.iterators import groupby_to_dict
from conda.common.url import has_platform, is_url, join_url
from conda.core.index import LAST_CHANNEL_URLS, get_index
from conda.core.link import PrefixSetup, UnlinkLinkTransaction
from conda.core.prefix_data import PrefixData
from conda.exceptions import ArgumentError
from conda.models.channel import prioritize_channels
from conda.models.enums import LinkType, PackageType
from conda.models.package_info import PackageInfo
