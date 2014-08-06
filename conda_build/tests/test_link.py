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

    def test_default_fatal(self):
        assert self.fatal

class TestBrokenLinkage(unittest.TestCase):

    # FIXME: these tests are relatively trivial, is more required?
    def test_full_message(self):
        broken_linkage = BrokenLinkage()
        assert broken_linkage.full_message

class TestExternalLinkage(unittest.TestCase):

    # FIXME: these tests are relatively trivial, is more required?
    def test_full_message(self):
        external_linkage = ExternalLinkage()
        assert external_linkage.full_message

class TestRecipeCorrectButBuildScriptBroken(unittest.TestCase):

    # FIXME: these tests are relatively trivial, is more required?
    def test_full_message(self):
        thing = RecipeCorrectButBuildScriptBroken()
        assert thing.full_message

class TestLinkErrors(unittest.TestCase):

    # FIXME: these tests are relatively trivial, is more required?
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

    # FIXME: these tests are relatively trivial, is more required?
    def test_summary_message(self):
        pass

