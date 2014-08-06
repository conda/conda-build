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

    def test_summary_message(self):
        pass

