#=============================================================================
# Imports
#=============================================================================
from __future__ import print_function
import sys

from abc import (
    ABCMeta,
    abstractmethod,
)

from textwrap import dedent

from conda.compat import with_metaclass

#=============================================================================
# Globals
#=============================================================================
final_message = dedent("""
    See http://conda.pydata.org/docs/link-errors.html for more info.

    Tip: run `conda build --ignore-link-errors` to ignore these errors and
    build the package anyway.  Note that the resulting package will not work
    if you install it on a different system *unless* that system also has all
    of the libraries listed above installed.
""")

#=============================================================================
# Classes
#=============================================================================
class BaseLinkErrorHandler(object):
    try_again = False
    allow_ignore_errors = True

    def __init__(self, metadata, exception, recipes, ignore_link_errors=False):
        self.metadata = metadata
        self.exception = exception
        self.recipes = recipes
        self.ignore_link_errors = ignore_link_errors

        self.errors = exception.errors

        self.names = set()
        self.broken = set()
        self.extern = {}

        self.new_library_recipe_needed = []
        self.recipe_needs_build_dependency_added = []

    def handle(self):
        self.categorize_errors()
        self.process_errors()
        self.finalize()

        if not self.ignore_link_errors:
            sys.exit(1)

    def finalize(self):
        """
        Called after all errors have been processed.  Intended to be used to
        print a final message informing the user of possible options for
        resolving link issues.
        """
        sys.stderr.write(final_message + '\n')

    @abstractmethod
    def categorize_errors(self):
        raise NotImplementedError()

    @abstractmethod
    def process_errors(self):
        raise NotImplementedError()


class LinkErrorHandler(with_metaclass(ABCMeta, BaseLinkErrorHandler)):
    try_again = False

    def categorize_errors(self):
        # We can't import conda_build.dll in the global scope because the
        # import order actually has us indirectly being imported by it (via
        # conda_build.config.resolve_link_error_handler()).  So, we import it
        # here.
        from conda_build.dll import (
            BrokenLinkage,
            ExternalLinkage,
            RecipeCorrectButBuildScriptBroken,
        )

        for error in self.errors:
            name = error.dependent_library_name
            self.names.add(name)
            # ExternalLinkage needs to come before BrokenLinkage as it derives
            # from it.
            if isinstance(error, ExternalLinkage):
                self.extern[name] = error.actual_link_target
            else:
                assert isinstance(error, BrokenLinkage)
                self.broken.add(name)

        # Check that there's no overlap between libraries being reported as
        # broken and extern at the same time.  (It's actually pretty
        # impressive if you've managed to get a build into that state.)
        for name in self.extern.keys():
            assert name not in self.broken, (name, self.broken)

        # Broken library links (e.g. ldd returned 'not found') need to be
        # fixed via proper compilation flags, usually.  Either that, or the
        # RPATH logic is busted.  Either way, broken libraries trump all other
        # link errors -- the resulting package absolutely will not load
        # correctly.
        if self.broken:
            for name in self.broken:
                assert name not in self.extern, (name, self.extern)

            # This message could be improved with some more information about
            # what was being li
            msg = (
                'Fatal error: broken linkage detected:\n    %s\n'

            )

        for (name, path) in self.extern.items():
            self.new_library_recipe_needed.append(path)

    def process_errors(self):
        # Post-processing of errors after they've been categorized.
        msgs = []
        if self.new_library_recipe_needed:
            msgs.append(
                'Error: external linkage detected to libraries living outside '
                'the build root:\n    %s\n' % (
                    '\n   '.join(self.new_library_recipe_needed)
                )
            )

        if self.broken:
            msgs.append(
                'Error: broken linkage detected for the following

            )
        for name in self.broken

        assert msgs
        sys.stderr.write('\n'.join(msgs) + '\n')
        self.error_messages = msgs


# vim:set ts=8 sw=4 sts=4 tw=78 et:
