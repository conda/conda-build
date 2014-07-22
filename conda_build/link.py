#=============================================================================
# Imports
#=============================================================================
import os

from continuum.debug import iset_trace

#=============================================================================
# Helpers
#=============================================================================

def handle_link_errors(metadata, exc, recipes):
    return LinkErrorHandler(metadata, exc, recipes)

#=============================================================================
# Classes
#=============================================================================
class LinkErrorHandler(object):
    try_again = False

    def __init__(self, metadata, exception, recipes):
        self.metadata = metadata
        self.exception = exception
        self.recipes = recipes

        self.errors = exception.errors

        self.names = set()
        self.broken = set()
        self.extern = {}

        self.new_library_recipe_needed = []
        self.recipe_needs_build_dependency_added = []

        self.categorize_errors()
        self.process_action_items()

    def categorize_errors(self):
        # We can't import conda_build.dll in the global scope because the
        # import order actually has us indirectly being imported by it (via
        # conda_build.config.resolve_link_error_handler()).  So, we import it
        # here.
        from conda_build.dll import (
            BrokenLinkage,
            ExternalLinkage,
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

        for name in self.broken:
            assert name not in self.extern, (name, self.extern)

        # Broken library links (e.g. ldd returned 'not found') need to be
        # fixed via proper compilation flags, usually.  Either that, or the
        # RPATH logic is busted.

        # (Should we be using metadata.info_index()['depends'] for this, or
        #  metadata.ms_spec()?  What's the difference?)
        dependencies = {}
        dependency_names = self.metadata.info_index()['depends']

        # How external links are handled depends on whether or not there's a
        # known package that provides that file and whether or not there's
        # already a dependency for that package in the recipe.
        for dependency in dependency_names:
            ix = dependency.find(' ')
            if ix != -1:
                # I presume dependencies with version specs appended will hit
                # this breakpoint (I want to poke around and see examples of
                # when this gets hit before writing version-spec handling
                # code).
                iset_trace()
                depname = dependency[:ix]
                depvers = dependency[ix+1:]
            else:
                depname = dependency
                depvers = None

            dependencies[depname] = depvers

        from ronda.model import Packages
        for (name, path) in self.extern.items():
            package = Packages.providing(name)
            if not package:
                # If there's no known package providing this library, we're
                # going to need to create a new conda package for it.
                self.new_library_recipe_needed.append(path)
                continue

            package_name = package.name
            if not package_name in dependencies:
                # This should be the most desirable situation: the wrong
                # package is being linked to simply because the dependency
                # is missing from the recipe.
                self.recipe_needs_build_dependency_added.append(package_name)
                continue


            # If the dependency *is* already there... then the build flags are
            # probably broken (LDFLAGS probably doesn't have -L$PREFIX/lib).
            # Assuming we implement support for automatically setting various
            # compiler flags before kicking off the build... this one will be
            # harder to fix automatically (if it happens even with correct
            # LDFLAGS set).  Also, libraries that trigger this path seem like
            # they would have already triggered the self.broken path earlier;
            # in fact, let's set a breakpoint if we hit this.  I'm curious to
            # see what will.
            iset_trace()
            print('name: %s, path: %s, package: %s' % (
                name,
                path,
                package,
            ))

    def process_action_items(self):
        # Ok, we've categorized all the link errors by this stage and placed
        # them in actionable bins.  Time to go through and action them!
        msgs = []
        if self.new_library_recipe_needed:
            iset_trace()
            msgs.append(
                'Error: external linkage detected to packages with no known '
                'conda equivalents:\n    %s\n' % (
                    '\n   '.join(self.new_library_recipe_needed)
                )
            )

        deps = self.recipe_needs_build_dependency_added
        if deps:
            msgs.append(
                'Error: the recipe %s needs to have one or more runtime '
                'dependencies added to it:\n    %s\n' % (
                    self.metadata.meta_path,
                    '\n'.join('    - %s' % d for d in deps),
                )
            )

        assert msgs
        import sys
        sys.stderr.write('\n'.join(msgs) + '\n')
        sys.exit(1)


# vim:set ts=8 sw=4 sts=4 tw=78 et:
