$ACTIVITIES = [
    "authors",
    "changelog",
    "tag",
    "push_tag",
    "ghrelease",
]

#
# Basic settings
#
$PROJECT = $GITHUB_REPO = "conda-build"
$GITHUB_ORG = "conda"
$AUTHORS_FILENAME = "AUTHORS.rst"

#
# Changelog settings
#
$CHANGELOG_FILENAME = "CHANGELOG.rst"
$CHANGELOG_PATTERN = "# current developments"
$CHANGELOG_HEADER = """# current developments
$VERSION ($RELEASE_DATE)
====================

"""
$CHANGELOG_CATEGORIES = (
    "Enhancements",
    "Bug fixes",
    "Deprecations",
    "Docs",
    "Other",
)


def title_formatter(category):
    s = category + '\n'
    s += "-" * (len(category) + 1)
    s += "\n\n"
    return s


$CHANGELOG_CATEGORY_TITLE_FORMAT = title_formatter
$CHANGELOG_AUTHORS_TITLE = "Contributors"
$CHANGELOG_AUTHORS_FORMAT = "* @{github}\n"
