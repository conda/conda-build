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
    LinkType,
    MatchSpec,
    PackageRecord,
    PrefixData,
    PrefixSetup,
    ProgressiveFetchExtract,
    UnlinkLinkTransaction,
    context,
    dashlist,
    env_vars,
    groupby_to_dict as groupby,
    normalized_version,
    on_win,
    prioritize_channels,
    stack_context_default,
)

from .dist import Dist
from .instructions import (
    ACTION_CODES,
    LINK,
    OP_ORDER,
    PREFIX,
    PRINT,
    PROGRESSIVEFETCHEXTRACT,
    UNLINK,
    UNLINKLINKTRANSACTION,
    commands,
)

log = getLogger(__name__)

# TODO: Remove conda/plan.py.  This module should be almost completely deprecated now.


def display_actions(
    actions, index, show_channel_urls=None, specs_to_remove=(), specs_to_add=()
):
    prefix = actions.get(PREFIX)
    builder = ["", "## Package Plan ##\n"]
    if prefix:
        builder.append("  environment location: %s" % prefix)
        builder.append("")
    if specs_to_remove:
        builder.append(
            "  removed specs: %s"
            % dashlist(sorted(str(s) for s in specs_to_remove), indent=4)
        )
        builder.append("")
    if specs_to_add:
        builder.append(
            "  added / updated specs: %s"
            % dashlist(sorted(str(s) for s in specs_to_add), indent=4)
        )
        builder.append("")
    print("\n".join(builder))

    if show_channel_urls is None:
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

    # package -> [oldver-oldbuild, newver-newbuild]
    packages = defaultdict(lambda: list(("", "")))
    features = defaultdict(lambda: list(("", "")))
    channels = defaultdict(lambda: list(("", "")))
    records = defaultdict(lambda: list((None, None)))
    linktypes = {}

    for prec in actions.get(LINK, []):
        assert isinstance(prec, PackageRecord)
        pkg = prec["name"]
        channels[pkg][1] = channel_str(prec)
        packages[pkg][1] = prec["version"] + "-" + prec["build"]
        records[pkg][1] = prec
        # TODO: this is a lie; may have to give this report after
        # UnlinkLinkTransaction.verify()
        linktypes[pkg] = LinkType.hardlink
        features[pkg][1] = ",".join(prec.get("features") or ())
    for prec in actions.get(UNLINK, []):
        assert isinstance(prec, PackageRecord)
        pkg = prec["name"]
        channels[pkg][0] = channel_str(prec)
        packages[pkg][0] = prec["version"] + "-" + prec["build"]
        records[pkg][0] = prec
        features[pkg][0] = ",".join(prec.get("features") or ())

    new = {p for p in packages if not packages[p][0]}
    removed = {p for p in packages if not packages[p][1]}
    # New packages are actually listed in the left-hand column,
    # so let's move them over there
    for pkg in new:
        for var in (packages, features, channels, records):
            var[pkg] = var[pkg][::-1]

    updated = set()
    downgraded = set()
    channeled = set()
    oldfmt = {}
    newfmt = {}
    empty = True
    if packages:
        empty = False
        maxpkg = max(len(p) for p in packages) + 1
        maxoldver = max(len(p[0]) for p in packages.values())
        maxnewver = max(len(p[1]) for p in packages.values())
        maxoldfeatures = max(len(p[0]) for p in features.values())
        maxnewfeatures = max(len(p[1]) for p in features.values())
        maxoldchannels = max(len(channel_filt(p[0])) for p in channels.values())
        maxnewchannels = max(len(channel_filt(p[1])) for p in channels.values())
        for pkg in packages:
            # That's right. I'm using old-style string formatting to generate a
            # string with new-style string formatting.
            oldfmt[pkg] = f"{{pkg:<{maxpkg}}} {{vers[0]:<{maxoldver}}}"
            if maxoldchannels:
                oldfmt[pkg] += " {channels[0]:<%s}" % maxoldchannels
            if features[pkg][0]:
                oldfmt[pkg] += " [{features[0]:<%s}]" % maxoldfeatures

            lt = LinkType(linktypes.get(pkg, LinkType.hardlink))
            lt = "" if lt == LinkType.hardlink else (" (%s)" % lt)
            if pkg in removed or pkg in new:
                oldfmt[pkg] += lt
                continue

            newfmt[pkg] = "{vers[1]:<%s}" % maxnewver
            if maxnewchannels:
                newfmt[pkg] += " {channels[1]:<%s}" % maxnewchannels
            if features[pkg][1]:
                newfmt[pkg] += " [{features[1]:<%s}]" % maxnewfeatures
            newfmt[pkg] += lt

            P0 = records[pkg][0]
            P1 = records[pkg][1]
            pri0 = P0.get("priority")
            pri1 = P1.get("priority")
            if pri0 is None or pri1 is None:
                pri0 = pri1 = 1
            try:
                if str(P1.version) == "custom":
                    newver = str(P0.version) != "custom"
                    oldver = not newver
                else:
                    # <= here means that unchanged packages will be put in updated
                    N0 = normalized_version(P0.version)
                    N1 = normalized_version(P1.version)
                    newver = N0 < N1
                    oldver = N0 > N1
            except TypeError:
                newver = P0.version < P1.version
                oldver = P0.version > P1.version
            oldbld = P0.build_number > P1.build_number
            newbld = P0.build_number < P1.build_number
            if (
                context.channel_priority
                and pri1 < pri0
                and (oldver or not newver and not newbld)
            ):
                channeled.add(pkg)
            elif newver:
                updated.add(pkg)
            elif pri1 < pri0 and (oldver or not newver and oldbld):
                channeled.add(pkg)
            elif oldver:
                downgraded.add(pkg)
            elif not oldbld:
                updated.add(pkg)
            else:
                downgraded.add(pkg)

    arrow = " --> "
    lead = " " * 4

    def format(s, pkg):
        chans = [channel_filt(c) for c in channels[pkg]]
        return lead + s.format(
            pkg=pkg + ":", vers=packages[pkg], channels=chans, features=features[pkg]
        )

    if new:
        print("\nThe following NEW packages will be INSTALLED:\n")
        for pkg in sorted(new):
            # New packages have been moved to the "old" column for display
            print(format(oldfmt[pkg], pkg))

    if removed:
        print("\nThe following packages will be REMOVED:\n")
        for pkg in sorted(removed):
            print(format(oldfmt[pkg], pkg))

    if updated:
        print("\nThe following packages will be UPDATED:\n")
        for pkg in sorted(updated):
            print(format(oldfmt[pkg] + arrow + newfmt[pkg], pkg))

    if channeled:
        print(
            "\nThe following packages will be SUPERSEDED by a higher-priority channel:\n"
        )
        for pkg in sorted(channeled):
            print(format(oldfmt[pkg] + arrow + newfmt[pkg], pkg))

    if downgraded:
        print("\nThe following packages will be DOWNGRADED:\n")
        for pkg in sorted(downgraded):
            print(format(oldfmt[pkg] + arrow + newfmt[pkg], pkg))

    print()


# ---------------------------- Backwards compat for conda-build --------------------------


def execute_actions(actions, index, verbose=False):  # pragma: no cover
    plan = _plan_from_actions(actions, index)
    execute_instructions(plan, index, verbose)


def _plan_from_actions(actions, index):  # pragma: no cover

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

    plan = _inject_UNLINKLINKTRANSACTION(plan, index, prefix)

    return plan


def _inject_UNLINKLINKTRANSACTION(plan, index, prefix):  # pragma: no cover
    # this is only used for conda-build at this point
    first_unlink_link_idx = next(
        (q for q, p in enumerate(plan) if p[0] in (UNLINK, LINK)), -1
    )
    if first_unlink_link_idx >= 0:
        grouped_instructions = groupby(lambda x: x[0], plan)
        unlink_dists = tuple(Dist(d[1]) for d in grouped_instructions.get(UNLINK, ()))
        link_dists = tuple(Dist(d[1]) for d in grouped_instructions.get(LINK, ()))
        unlink_dists, link_dists = _handle_menuinst(unlink_dists, link_dists)

        if isdir(prefix):
            unlink_precs = tuple(index[d] for d in unlink_dists)
        else:
            # there's nothing to unlink in an environment that doesn't exist
            # this is a hack for what appears to be a logic error in conda-build
            # caught in tests/test_subpackages.py::test_subpackage_recipes[python_test_dep]
            unlink_precs = ()
        link_precs = tuple(index[d] for d in link_dists)

        pfe = ProgressiveFetchExtract(link_precs)
        pfe.prepare()

        stp = PrefixSetup(prefix, unlink_precs, link_precs, (), [], ())
        plan.insert(
            first_unlink_link_idx, (UNLINKLINKTRANSACTION, UnlinkLinkTransaction(stp))
        )
        plan.insert(first_unlink_link_idx, (PROGRESSIVEFETCHEXTRACT, pfe))

    return plan


def _handle_menuinst(unlink_dists, link_dists):  # pragma: no cover
    if not on_win:
        return unlink_dists, link_dists

    # Always link/unlink menuinst first/last on windows in case a subsequent
    # package tries to import it to create/remove a shortcut

    # unlink
    menuinst_idx = next(
        (q for q, d in enumerate(unlink_dists) if d.name == "menuinst"), None
    )
    if menuinst_idx is not None:
        unlink_dists = (
            *unlink_dists[:menuinst_idx],
            *unlink_dists[menuinst_idx + 1 :],
            *unlink_dists[menuinst_idx : menuinst_idx + 1],
        )

    # link
    menuinst_idx = next(
        (q for q, d in enumerate(link_dists) if d.name == "menuinst"), None
    )
    if menuinst_idx is not None:
        link_dists = (
            *link_dists[menuinst_idx : menuinst_idx + 1],
            *link_dists[:menuinst_idx],
            *link_dists[menuinst_idx + 1 :],
        )

    return unlink_dists, link_dists


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
            solver._index = {prec: prec for prec in index.values()}
        txn = solver.solve_for_transaction(prune=prune, ignore_pinned=not pinned)
        prefix_setup = txn.prefix_setups[prefix]
        actions = get_blank_actions(prefix)
        actions[UNLINK].extend(Dist(prec) for prec in prefix_setup.unlink_precs)
        actions[LINK].extend(Dist(prec) for prec in prefix_setup.link_precs)
        return actions


def get_blank_actions(prefix):  # pragma: no cover
    actions = defaultdict(list)
    actions[PREFIX] = prefix
    actions[OP_ORDER] = (
        UNLINK,
        LINK,
    )
    return actions


def execute_instructions(plan, index=None, verbose=False):
    """Execute the instructions in the plan

    :param plan: A list of (instruction, arg) tuples
    :param index: The meta-data index
    :param verbose: verbose output
    """
    log.debug("executing plan %s", plan)

    state = {"i": None, "prefix": context.root_prefix, "index": index}

    for instruction, arg in plan:
        log.debug(" %s(%r)", instruction, arg)

        cmd = commands[instruction]

        if callable(cmd):
            cmd(state, arg)
