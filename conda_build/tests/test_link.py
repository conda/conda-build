import unittest

from conda_build.build import (
    BuildRoot,
)

from conda_build.link import (
    LinkError,
    BrokenLinkage,
    ExternalLinkage,
    RecipeCorrectButBuildScriptBroken,
    LinkErrors,
    BaseLinkErrorHandler,
    LinkErrorHandler,
)


class TestLinkError(unittest.TestCase, LinkError):

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)
        LinkError.__init__(self, *args, **kwargs)

    def test_default_fatal(self):
        assert self.fatal

class TestBrokenLinkage(TestLinkError, BrokenLinkage):
    # subclass TestLinkError to ensure fatal

    def __init__(self, *args, **kwargs):
        TestLinkError.__init__(self, *args, **kwargs)
        BrokenLinkage.__init__(self, *args, **kwargs)

    def test_full_message(self):
        assert self.full_message

class TestExternalLinkage(unittest.TestCase, ExternalLinkage):

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)
        ExternalLinkage.__init__(self, *args, **kwargs)

    def test_full_message(self):
        assert self.full_message

class TestRecipeCorrectButBuildScriptBroken(TestLinkError,
        RecipeCorrectButBuildScriptBroken):
    # subclass TestLinkError to ensure fatal

    def __init__(self, *args, **kwargs):
        TestLinkError.__init__(self, *args, **kwargs)
        RecipeCorrectButBuildScriptBroken.__init__(self, *args, **kwargs)

class TestLinkErrors(unittest.TestCase):

    def test_has_errors(self):
        build_root = BuildRoot()
        make_link_errors = lambda: LinkErrors(build_root)
        self.assertRaises(AssertionError, make_link_errors)

    def test_message(self):
        build_root = BuildRoot()
        build_root.link_errors = [1]
        link_errors = LinkErrors(build_root)
        assert link_errors.message

class TestLinkErrorHandler(unittest.TestCase):
    ''' BaseLinkErrorHandler expects constructor args metadata, exception, recipes
    it uses exception.errors
    '''

    def make_linkerrors(self, num_broken=1, num_external=1):
        # make some 'LinkError's
        # rcbbsb = RecipeCorrectButBuildScriptBroken(<stuff>)
        def make_broken_linkage(idx):
            return BrokenLinkage('to%s' % idx, 'from%s' % idx)
        def make_external_linkage(idx):
            return ExternalLinkage('to%s' % idx, 'from%s' % idx,
                    'actual%s' % idx)
        broken_ids = range(0, num_broken)
        external_ids= range(num_broken, num_broken + num_external)
        _link_errors = []
        _link_errors += map(make_broken_linkage, broken_ids)
        _link_errors += map(make_external_linkage, external_ids)
        # pack them into a build_root
        build_root = BuildRoot()
        build_root.link_errors = _link_errors
        return LinkErrors(build_root)

    def make_linkerrorhandler(self, num_broken=1, num_external=1):
        linkerrors = self.make_linkerrors(num_broken=num_broken,
                num_external=num_external)
        link_error_handler = LinkErrorHandler(metadata=None,
                exception=linkerrors, recipes=None)
        return link_error_handler

    def test_categorize_errors(self):
        ''' uses self.errors as a list of {ExternalLinkage, BrokenLnkage}
            modifies extern, broken, names, new_library_recipe_needed
        '''

        num_broken = 1
        num_external = 1
        link_error_handler = self.make_linkerrorhandler(num_broken=num_broken,
                num_external=num_external)
        link_error_handler._categorize_errors()
        assert link_error_handler.names
        assert len(link_error_handler.names) == num_broken + num_external
        assert link_error_handler.broken
        assert len(link_error_handler.broken) == num_broken
        assert link_error_handler.extern
        assert len(link_error_handler.extern) == num_external
        assert link_error_handler.new_library_recipe_needed
        assert len(link_error_handler.new_library_recipe_needed) == num_external

    def test_process_errors(self):
        ''' uses self.new_library_recipe_needed, self.broken
            modifes error_messages
        '''
        # FIXME: actually test _process_errors
        assert self.make_linkerrors()
