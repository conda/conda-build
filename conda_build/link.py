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
final_message = None

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
            "See http://conda.pydata.org/docs/link-errors.html#broken "
            "for more information."
    )
    _reasons = [
            '\t- when a library is both a build and a run requirement,\n'
            '\t\tbut only added as one of the two in meta.yaml\n'
            '\t\t(esp. libgfortran)',
            '\t- during development of conda build',
            ]
    _summary_message = '\n'.join([
        dedent('''
        Broken linkage errors are usually caused by conda build
        incorrectly setting the RPATH during post-build processing
        steps.  This will typically happen
        ''').strip(),
        '\n'.join(_reasons),
        dedent('''
        If you're running into these errors trying
        to build conda packages, there is something in your
        environment adversely affecting our RPATH logic.
        ''').strip()
        ])


    def __init__(self, *args):
        SlotObject.__init__(self, *args)
        # xxx: make __repr__() use this instead?  Main use case is for each
        # type of error (i.e. BrokenLinkage), print out the prefix, then all
        # affected files, then the summary.  This will probably be done at the
        # LinkErrors class level maybe?  Dunno', hadn't thought that far
        # through.
        self.full_message = self.make_full_message(self.description)

    @classmethod
    def make_full_message(cls, description):
        return '\n\n'.join([
            cls.prefix,
            description,
            cls.summary_message(),
            cls.link,
            ])

    @property
    def description(self):
        return "    %s can't find link target '%s'" % (
            self.library.name,
            self.dependent_library_name,
        )

    # xxx todo:
    def __repr__(self):
        super_repr = super(BrokenLinkage, self).__repr__()
        return '%s(%s)' % (super_repr, self.description)

    def __str__(self):
        return '    %s: %s' % (self.__class__.__name__, self.description.lstrip())

    @staticmethod
    def summary_message():
        msg = None
        if is_linux:
            msg = BrokenLinkage._summary_message
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

    prefix = "External linkage detected:"

    link = (
            'See http://conda.pydata.org/docs/link-errors.html#external '
            'for more information.'
            )

    # FIXME: get proper language from Trent
    _summary_message = dedent('''
        Tip: run `conda build --ignore-link-errors` to ignore these errors and
        build the package anyway.  Note that the resulting package will not work
        if you install it on a different system *unless* that system also has all
        of the libraries listed above installed.
    ''').strip()

    @property
    def description(self):
        return '    %s is linking to library outside of build path: %s' % (
                self.library.name,
                self.actual_link_target,
        )

    @staticmethod
    def summary_message():
        # FIXME: remove this method?
        #        if this summary_message is same as BrokenLinkage, we can just
        #        fall back to BrokenLinkage's method.  If not, we should change
        #        the string below.  Perhaps the appended html link as well
        msg = None
        if is_linux:
            msg = ExternalLinkage._summary_message
        else:
            raise NotImplementedError()
        return msg

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

    def __repr__(self):
        super_repr = super(LinkErrors, self).__repr__()
        return '%s(%s)' % (super_repr, self.message)

    def __str__(self):
        return repr(self)

class BaseLinkErrorHandler(object):
    try_again = False
    allow_ignore_errors = True

    def __init__(self, metadata, exception, recipes, ignore_link_errors=True):
        # FIXME: name ignore_link_errors something more descriptive
        #        perhaps ignore_extern_errors since we allow external linkages
        #        but never allow missing linkages
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

    def handle(self, simulate=False):
        ''' Coordinate the method calls to handle link errors

        The primary external method of BaseLinkErrorHandler
        '''

        self._categorize_errors()
        self._process_errors()
        self._finalize()

        exit_on_extern = self.extern and not self.ignore_link_errors
        if self.broken or exit_on_extern:
            if not simulate:
                #sys.exit(1)
                sys.exit(dedent('''
                    CONDA BUILD: linkage issues detected
                    Build failed!!!
                    EXITING!!!
                    ''')).strip()

    def _finalize(self):
        '''
        Called after all errors have been processed.  Intended to be used to
        print a final message informing the user of possible options for
        resolving link issues.
        '''
        if final_message:
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
        get_name = lambda error: error.dependent_library_name
        is_external = lambda error: isinstance(error, ExternalLinkage)
        is_not_external = lambda error: not is_external(error)
        is_broken = lambda error: isinstance(error, BrokenLinkage)

        external_list = filter(is_external, self.errors)
        # broken is not external because external derives from broken
        broken_list = filter(is_not_external, self.errors)
        external_names = map(get_name, external_list)
        broken_names = map(get_name, broken_list)

        assert all(map(is_broken, broken_list))
        # Check that there's no overlap between libraries being reported as
        # broken and extern at the same time.  (It's actually pretty
        # impressive if you've managed to get a build into that state.)
        assert_disjoint(external_names, broken_names)

        self.names = set(external_names + broken_names)
        self.extern = external_list
        self.broken = broken_list
        self.new_library_recipe_needed = [
                _ext for _ext in self.extern
                ]

    def _process_errors(self):
        ''' Create a single unified message to show to the user

        To avoid repeating messages for the same depedency.
        '''

        # Post-processing of errors after they've been categorized.
        msgs = []
        if self.extern:
            description = '\n'.join(map(str, self.extern))
            full_message = ExternalLinkage.make_full_message(description)
            msgs.append(full_message)

        # Broken library links (e.g. ldd returned 'not found') need to be
        # fixed via proper compilation flags, usually.  Either that, or the
        # RPATH logic is busted.  Either way, broken libraries trump all other
        # link errors -- the resulting package absolutely will not load
        # correctly.
        if self.broken:
            # This message could be improved with some more information about
            # what was being li
            description = '\n'.join(map(str, self.broken))
            full_message = BrokenLinkage.make_full_message(description)
            msgs.append(full_message)

        assert msgs
        header = "\n\nCONDA BUILD\n"
        sys.stderr.write(header + '\n\n\n'.join(msgs) + '\n')
        self.error_messages += msgs


# vim:set ts=8 sw=4 sts=4 tw=78 et:
