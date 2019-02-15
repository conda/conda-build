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
    def __init__(self, conda_exception=None, packages=None, subdir=None, *args, **kwargs):
        self.subdir = subdir
        self.matchspecs = []
        if packages:
            self.packages = packages
        else:
            self.packages = packages or []
            for line in str(conda_exception).splitlines():
                if not line.startswith('  - '):
                    continue
                pkg = line.lstrip('  - ').split(' -> ')[-1]
                self.matchspecs.append(pkg)
                pkg = pkg.strip().split(' ')[0].split('=')[0].split('[')[0]
                self.packages.append(pkg)
        if not self.packages:
            raise RuntimeError("failed to parse packages from exception:"
                               " {}".format(str(conda_exception)))

    def __str__(self):
        return self.message

    @property
    def message(self):
        return "Unsatisfiable dependencies for platform {}: {}".format(self.subdir,
                                                                       set(self.matchspecs))


class RecipeError(CondaBuildException):
    pass


class BuildLockError(CondaBuildException):
    """ Raised when we failed to acquire a lock. """


class OverLinkingError(RuntimeError):
    def __init__(self, error, *args):
        self.error = error
        self.msg = "overlinking check failed \n%s" % (error)
        super(OverLinkingError, self).__init__(self.msg)


class OverDependingError(RuntimeError):
    def __init__(self, error, *args):
        self.error = error
        self.msg = "overdepending check failed \n%s" % (error)
        super(OverDependingError, self).__init__(self.msg)


class RunPathError(RuntimeError):
    def __init__(self, error, *args):
        self.error = error
        self.msg = "runpaths check failed \n%s" % (error)
        super(RunPathError, self).__init__(self.msg)
