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
from os.path import basename, isdir

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

from .instructions import (
    ACTION_CODES,
    LINK,
    OP_ORDER,
    PREFIX,
    PRINT,
    PROGRESSIVEFETCHEXTRACT,
    UNLINKLINKTRANSACTION,
    commands,
)

log = getLogger(__name__)

# TODO: Remove conda/plan.py.  This module should be almost completely deprecated now.


def display_actions(actions):
    prefix = actions.get(PREFIX)
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

    for prec in actions.get(LINK, []):
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


# ---------------------------- Backwards compat for conda-build --------------------------


def execute_actions(actions, verbose=False):  # pragma: no cover
    plan = _plan_from_actions(actions)
    execute_instructions(plan, verbose)


def _plan_from_actions(actions):  # pragma: no cover

    if OP_ORDER in actions and actions[OP_ORDER]:
        op_order = actions[OP_ORDER]
    else:
        op_order = ACTION_CODES

    assert PREFIX in actions and actions[PREFIX]
    prefix = actions[PREFIX]
    plan = [(PREFIX, "%s" % prefix)]

    unlink_link_transaction = actions.get(UNLINKLINKTRANSACTION)
    if unlink_link_transaction:
        raise RuntimeError()
        # progressive_fetch_extract = actions.get(PROGRESSIVEFETCHEXTRACT)
        # if progressive_fetch_extract:
        #     plan.append((PROGRESSIVEFETCHEXTRACT, progressive_fetch_extract))
        # plan.append((UNLINKLINKTRANSACTION, unlink_link_transaction))
        # return plan

    log.debug(f"Adding plans for operations: {op_order}")
    for op in op_order:
        if op not in actions:
            log.trace(f"action {op} not in actions")
            continue
        if not actions[op]:
            log.trace(f"action {op} has None value")
            continue
        if "_" not in op:
            plan.append((PRINT, "%sing packages ..." % op.capitalize()))
        for arg in actions[op]:
            log.debug(f"appending value {arg} for action {op}")
            plan.append((op, arg))

    plan = _inject_UNLINKLINKTRANSACTION(plan, prefix)

    return plan


def _inject_UNLINKLINKTRANSACTION(plan, prefix):  # pragma: no cover
    # this is only used for conda-build at this point
    first_unlink_link_idx = next(
        (q for q, p in enumerate(plan) if p[0] in (LINK,)), -1
    )
    if first_unlink_link_idx >= 0:
        link_precs = tuple(prec for action, prec in plan if action == LINK)
        link_precs = _handle_menuinst(link_precs)

        pfe = ProgressiveFetchExtract(link_precs)
        pfe.prepare()

        stp = PrefixSetup(prefix, (), link_precs, (), [], ())
        plan.insert(
            first_unlink_link_idx, (UNLINKLINKTRANSACTION, UnlinkLinkTransaction(stp))
        )
        plan.insert(first_unlink_link_idx, (PROGRESSIVEFETCHEXTRACT, pfe))

    return plan


def _handle_menuinst(link_precs):  # pragma: no cover
    if not on_win:
        return link_precs

    # Always link menuinst first/last on windows in case a subsequent
    # package tries to import it to create/remove a shortcut

    # link
    menuinst_idx = next(
        (q for q, d in enumerate(link_precs) if d.name == "menuinst"), None
    )
    if menuinst_idx is not None:
        link_precs = (
            *link_precs[menuinst_idx : menuinst_idx + 1],
            *link_precs[:menuinst_idx],
            *link_precs[menuinst_idx + 1 :],
        )

    return link_precs


def install_actions(
    prefix,
    index,
    specs,
    force=False,
    only_names=None,
    always_copy=False,
    pinned=True,
    update_deps=True,
    prune=False,
    channel_priority_map=None,
    is_update=False,
    minimal_hint=False,
):  # pragma: no cover
    # this is for conda-build
    with env_vars(
        {
            "CONDA_ALLOW_NON_CHANNEL_URLS": "true",
            "CONDA_SOLVER_IGNORE_TIMESTAMPS": "false",
        },
        stack_callback=stack_context_default,
    ):
        if channel_priority_map:
            channel_names = IndexedSet(
                Channel(url).canonical_name for url in channel_priority_map
            )
            channels = IndexedSet(Channel(cn) for cn in channel_names)
            subdirs = IndexedSet(basename(url) for url in channel_priority_map)
        else:
            # a hack for when conda-build calls this function without giving channel_priority_map
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
        txn = solver.solve_for_transaction(prune=prune, ignore_pinned=not pinned)
        prefix_setup = txn.prefix_setups[prefix]
        actions = get_blank_actions(prefix)
        actions[LINK].extend(prec for prec in prefix_setup.link_precs)
        return actions


def get_blank_actions(prefix):  # pragma: no cover
    actions = defaultdict(list)
    actions[PREFIX] = prefix
    actions[OP_ORDER] = (
        LINK,
    )
    return actions


def execute_instructions(plan, verbose=False):
    """Execute the instructions in the plan

    :param plan: A list of (instruction, arg) tuples
    :param verbose: verbose output
    """
    log.debug("executing plan %s", plan)

    for instruction, arg in plan:
        log.debug(" %s(%r)", instruction, arg)

        cmd = commands[instruction]

        if callable(cmd):
            cmd(arg)
