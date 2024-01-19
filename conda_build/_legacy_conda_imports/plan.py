# Copyright (C) 2012 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
Handle the planning of installs and their execution.

NOTE:
    conda.install uses canonical package names in its interface functions,
    whereas conda.resolve uses package filenames, as those are used as index
    keys.  We try to keep fixes to this "impedance mismatch" local to this
    module.
"""

from collections import defaultdict
from logging import getLogger

from .conda_imports import (
    DEFAULTS_CHANNEL_NAME,
    LAST_CHANNEL_URLS,
    UNKNOWN_CHANNEL,
    Channel,
    IndexedSet,
    MatchSpec,
    PackageRecord,
    PrefixData,
    PrefixSetup,
    ProgressiveFetchExtract,
    UnlinkLinkTransaction,
    context,
    env_vars,
    on_win,
    prioritize_channels,
    stack_context_default,
)

PREFIX_ACTION = "PREFIX"
LINK_ACTION = "LINK"

log = getLogger(__name__)


def display_actions(actions):
    prefix = actions.get(PREFIX_ACTION)
    builder = ["", "## Package Plan ##\n"]
    if prefix:
        builder.append("  environment location: %s" % prefix)
        builder.append("")
    print("\n".join(builder))

    show_channel_urls = context.show_channel_urls

    def channel_str(rec):
        if rec.get("schannel"):
            return rec["schannel"]
        if rec.get("url"):
            return Channel(rec["url"]).canonical_name
        if rec.get("channel"):
            return Channel(rec["channel"]).canonical_name
        return UNKNOWN_CHANNEL

    def channel_filt(s):
        if show_channel_urls is False:
            return ""
        if show_channel_urls is None and s == DEFAULTS_CHANNEL_NAME:
            return ""
        return s

    packages = defaultdict(lambda: "")
    features = defaultdict(lambda: "")
    channels = defaultdict(lambda: "")

    for prec in actions.get(LINK_ACTION, []):
        assert isinstance(prec, PackageRecord)
        pkg = prec["name"]
        channels[pkg] = channel_filt(channel_str(prec))
        packages[pkg] = prec["version"] + "-" + prec["build"]
        features[pkg] = ",".join(prec.get("features") or ())

    fmt = {}
    if packages:
        maxpkg = max(len(p) for p in packages) + 1
        maxver = max(len(p) for p in packages.values())
        maxfeatures = max(len(p) for p in features.values())
        maxchannels = max(len(p) for p in channels.values())
        for pkg in packages:
            # That's right. I'm using old-style string formatting to generate a
            # string with new-style string formatting.
            fmt[pkg] = f"{{pkg:<{maxpkg}}} {{vers:<{maxver}}}"
            if maxchannels:
                fmt[pkg] += " {channel:<%s}" % maxchannels
            if features[pkg]:
                fmt[pkg] += " [{features:<%s}]" % maxfeatures

    lead = " " * 4

    def format(s, pkg):
        return lead + s.format(
                pkg=pkg + ":", vers=packages[pkg], channel=channels[pkg], features=features[pkg]
        )

    if packages:
        print("\nThe following NEW packages will be INSTALLED:\n")
        for pkg in sorted(packages):
            print(format(fmt[pkg], pkg))
    print()


def execute_actions(actions):
    assert PREFIX_ACTION in actions and actions[PREFIX_ACTION]
    prefix = actions[PREFIX_ACTION]

    if LINK_ACTION not in actions:
        log.debug(f"action {LINK_ACTION} not in actions")
        return

    link_precs = actions[LINK_ACTION]
    if not link_precs:
        log.debug(f"action {LINK_ACTION} has None value")
        return

    if on_win:
        # Always link menuinst first/last on windows in case a subsequent
        # package tries to import it to create/remove a shortcut
        link_precs = (
            [p for p in link_precs if p.name == "menuinst"] +
            [p for p in link_precs if p.name != "menuinst"]
        )

    progressive_fetch_extract = ProgressiveFetchExtract(link_precs)
    progressive_fetch_extract.prepare()

    stp = PrefixSetup(prefix, (), link_precs, (), [], ())
    unlink_link_transaction = UnlinkLinkTransaction(stp)

    log.debug(" %s(%r)", "PROGRESSIVEFETCHEXTRACT", progressive_fetch_extract)
    progressive_fetch_extract.execute()
    log.debug(" %s(%r)", "UNLINKLINKTRANSACTION", unlink_link_transaction)
    unlink_link_transaction.execute()


def install_actions(prefix, index, specs):
    with env_vars(
        {
            "CONDA_ALLOW_NON_CHANNEL_URLS": "true",
            "CONDA_SOLVER_IGNORE_TIMESTAMPS": "false",
        },
        stack_callback=stack_context_default,
    ):
        # a hack since in conda-build we don't track channel_priority_map
        if LAST_CHANNEL_URLS:
            channel_priority_map = prioritize_channels(LAST_CHANNEL_URLS)
            channels = IndexedSet(Channel(url) for url in channel_priority_map)
            subdirs = (
                IndexedSet(
                    subdir for subdir in (c.subdir for c in channels) if subdir
                )
                or context.subdirs
            )
        else:
            channels = subdirs = None

        specs = tuple(MatchSpec(spec) for spec in specs)

        PrefixData._cache_.clear()

        solver_backend = context.plugin_manager.get_cached_solver_backend()
        solver = solver_backend(prefix, channels, subdirs, specs_to_add=specs)
        if index:
            # Solver can modify the index (e.g., Solver._prepare adds virtual
            # package) => Copy index (just outer container, not deep copy)
            # to conserve it.
            solver._index = index.copy()
        txn = solver.solve_for_transaction(prune=False, ignore_pinned=False)
        prefix_setup = txn.prefix_setups[prefix]
        actions = {
            PREFIX_ACTION: prefix,
            LINK_ACTION: [prec for prec in prefix_setup.link_precs],
        }
        return actions
