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

from conda_build.utils import (
    SlotObject,
    is_linux,
    is_darwin,
    is_win32,
)


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
class LinkError(Exception):
    ''' Base class for Exceptions related to library linkages

    fatal, when set to True, indicates that this link error can't be ignored
    by the --ignore-link-errors command line argument or ignore_link_errors
    in ~/.condarc.  General rule of thumb: use `fatal = True` if there is no
    possible way this package will work, e.g. there is a library being
    reported as 'not found' by ldd.

    Atributes:
        fatal: should this LinkError preclude a successful build
    '''

    fatal = True

class BrokenLinkage(SlotObject, LinkError):
    ''' Provide informative methods and members related to 'LinkError's

    Attributes:
        prefix: preamble to BrokenLinkage error message
        library: target library (library linked to) that has issues
        dependent_library_name: originating library (library linked from) that
            has issues
        description: property to give a concise summary of this particular
            LinkError.

    '''

    __slots__ = (
        'library',
        'dependent_library_name',
    )

    prefix = "Broken dynamic library linkage detected:"
    link = (
            "\nSee http://conda.pydata.org/docs/link-errors.html#broken "
            "for more information."
    )

    def __init__(self, *args):
        SlotObject.__init__(self, *args)
        # xxx: make __repr__() use this instead?  Main use case is for each
        # type of error (i.e. BrokenLinkage), print out the prefix, then all
        # affected files, then the summary.  This will probably be done at the
        # LinkErrors class level maybe?  Dunno', hadn't thought that far
        # through.
        self.full_message = '\n'.join([
            self.prefix,
            self.description,
            self.summary_message(),
            self.link,
            ]
        )

    @property
    def description(self):
        return "    %s can't find link target '%s'" % (
            self.library,
            self.dependent_library_name,
        )

    # xxx todo:
    def __repr__(self):
        return '\n'.join([self.prefix, self.description])

    def __str__(self):
        return repr(self)

    @staticmethod
    def summary_message():
        msg = None
        if is_linux:
            msg = (
                "Broken linkage errors are usually caused by conda build "
                "incorrectly setting the RPATH during post-build processing "
                "steps.  This will typically only happen during development "
                "of conda build.  If you're running into these errors trying "
                "to build conda packages, there is something in your "
                "environment adversely affecting our RPATH logic."
            )
        else:
            raise NotImplementedError()
        return msg

class ExternalLinkage(BrokenLinkage):
    ''' A non-fatal linkage to a library that exists outside of the lib dir

    FIXME: do slots need to be documented?
    FIXME: language in __repr__ can't be right, can it?  We can find it, its
    just outside of prefix dir
    '''

    # External linkage is the only link error we allow people to ignore via
    # --ignore-external-linkage-errors.
    fatal = False

    __slots__ = (
        BrokenLinkage.__slots__ +
        ('actual_link_target',)
    )

    def __repr__(self):
        return (
            "External linkage detected:\n"
            "    %s: wants to link to %s, but can't find it" % (
                self.library,
                self.dependent_library_name,
            )
        )

    @staticmethod
    def summary_message():
        # FIXME: remove this method?
        #        if this summary_message is same as BrokenLinkage, we can just
        #        fall back to BrokenLinkage's method.  If not, we should change
        #        the string below.  Perhaps the appended html link as well
        return BrokenLinkage.summary_message()

class RecipeCorrectButBuildScriptBroken(BrokenLinkage):
    # FIXME: should I inherit from ExternalLinkage?
    # If so, I need to set fatal back to True
    # If not, then my __slots__ should extend BrokenLinkage, not ExternalLnkage
    __slots__ = (
        ExternalLinkage.__slots__ +
        ('expected_link_target',)
    )

class LinkErrors(Exception):
    ''' LinkErrors allows reporting multiple 'LinkError's simultaneously

    Converts a BuildRoot's link_errors into a single message

    Attributes:
        message: concatenation of 'repr' of each build_root.link_errors element
        build_root: copy of build_root
        errors: copy of build_root.link_errors
        allow_ignore_link_errors: ???
    '''

    def __init__(self, build_root):
        self.allow_ignore_link_errors = None
        self.build_root = build_root
        self.errors = build_root.link_errors
        assert self.errors
        #
        def errors_to_str(errors):
            error_to_str = lambda error: '    %s' % repr(error)
            errors_as_str = '\n'.join(map(error_to_str, errors))
            return 'Link errors:\n%s\n' % errors_as_str
        self.message = errors_to_str(self.errors)

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
        self.error_messages = []

    def handle(self):
        ''' Coordinate the method calls to handle link errors

        The primary external method of BaseLinkErrorHandler
        '''

        self._categorize_errors()
        self._process_errors()
        self._finalize()

        if self.broken or not self.ignore_link_errors:
            sys.exit(1)

    def _finalize(self):
        """
        Called after all errors have been processed.  Intended to be used to
        print a final message informing the user of possible options for
        resolving link issues.
        """
        sys.stderr.write(final_message + '\n')

    @abstractmethod
    def _categorize_errors(self):
        raise NotImplementedError()

    @abstractmethod
    def _process_errors(self):
        raise NotImplementedError()


def assert_disjoint(left, right):
    intersection = set(left).intersection(right)
    assert not intersection, (intersection, left, right)


class LinkErrorHandler(with_metaclass(ABCMeta, BaseLinkErrorHandler)):
    try_again = False

    def _categorize_errors(self):
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
        assert_disjoint(self.extern.keys(), self.broken)

        extern_paths = self.extern.values()
        self.new_library_recipe_needed.extend(extern_paths)

    def _process_errors(self):
        ''' Create a single unified message to show to the user

        To avoid repeating messages for the same depedency.
        '''

        # Post-processing of errors after they've been categorized.
        msgs = []
        if self.new_library_recipe_needed:
            error_str = '\n    '.join(self.new_library_recipe_needed)
            msg_template = (
                'Error: external linkage detected to libraries living outside '
                'the build root:\n    %s\n'
            )
            msg = msg_template % error_str
            msgs.append(msg)

        # Broken library links (e.g. ldd returned 'not found') need to be
        # fixed via proper compilation flags, usually.  Either that, or the
        # RPATH logic is busted.  Either way, broken libraries trump all other
        # link errors -- the resulting package absolutely will not load
        # correctly.
        if self.broken:
            # This message could be improved with some more information about
            # what was being li
            error_str = '\n    '.join(self.broken)
            msg_template = (
                'Fatal error: broken linkage detected for the following '
                'packages:\n    %s\n'
            )
            msg = msg_template % error_str
            msgs.append(msg)

        assert msgs
        sys.stderr.write('\n'.join(msgs) + '\n')
        self.error_messages += msgs


# vim:set ts=8 sw=4 sts=4 tw=78 et:
