$ACTIVITIES = [
    'authors',
    'changelog',
    #'tag',
    ]

#
# Author settings
#
$AUTHORS_FILENAME = "AUTHORS.txt"

#
# Changelog settings
#
$CHANGELOG_FILENAME = "CHANGELOG.txt"
$CHANGELOG_PATTERN = "# current developments"
$CHANGELOG_HEADER = """# current developments
$RELEASE_DATE $VERSION:
------------------

"""
$CHANGELOG_CATEGORIES = (
    "Enhancements",
    "Bug fixes",
    "Deprecations",
    "Docs",
    "Other",
    )


def title_formatter(category):
    s = category + ':\n'
    s += "-" * (len(category) + 1)
    s += "\n\n"
    return s


$CHANGELOG_CATEGORY_TITLE_FORMAT = title_formatter
$CHANGELOG_AUTHORS_TITLE = "Contributors"
$CHANGELOG_AUTHORS_FORMAT = "* @{github}\n"
