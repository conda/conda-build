import textwrap
SEPARATOR = "-" * 70

indent = lambda s: textwrap.fill(textwrap.dedent(s))


class CondaBuildException(Exception):
    pass


class YamlParsingError(CondaBuildException):
    pass


class UnableToParse(YamlParsingError):
    def __init__(self, original, *args, **kwargs):
        super(UnableToParse, self).__init__(*args, **kwargs)
        self.original = original

    def error_msg(self):
        return "\n".join([
            SEPARATOR,
            self.error_body(),
            self.indented_exception(),
        ])

    def error_body(self):
        return "\n".join([
            "Unable to parse meta.yaml file\n",
        ])

    def indented_exception(self):
        orig = str(self.original)
        indent = lambda s: s.replace("\n", "\n--> ")
        return "Error Message:\n--> {}\n\n".format(indent(orig))


class UnableToParseMissingJinja2(UnableToParse):
    def error_body(self):
        return "\n".join([
            super(UnableToParseMissingJinja2, self).error_body(),
            indent("""\
                It appears you are missing jinja2.  Please install that
                package, then attempt to build.
            """),
        ])


class UnableToParseMissingSetuptoolsDependencies(CondaBuildException):
    pass


class VerifyError(CondaBuildException):
    def __init__(self, error, script, *args):
        self.error = error
        self.script = script
        self.msg = "%s failed to verify\n%s" % (script, error)
        super(VerifyError, self).__init__(self.msg)


class DependencyNeedsBuildingError(CondaBuildException):
    def __init__(self, CondaException, *args, **kwargs):
        self.packages = []
        for line in str(CondaException).splitlines():
            if not line.startswith('  - '):
                continue
            pkg = line.lstrip('  - ').split(' -> ')[-1]
            pkg = pkg.strip().split(' ')[0]
            self.packages.append(pkg)
        self.message = str(CondaException)
        if not self.packages:
            raise RuntimeError("failed to parse packages from exception:"
                               " {}".format(str(CondaException)))


class UnsatisfiableVariantError(CondaBuildException):
    pass
