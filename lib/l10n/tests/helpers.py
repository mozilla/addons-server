from babel.messages.extract import extract
from l10n.management.commands.extract import (DEFAULT_KEYWORDS,
                                              COMMENT_TAGS,
                                              OPTIONS_MAP)


def fake_extract_from_dir(filename, fileobj, method,
                          options=OPTIONS_MAP, keywords=DEFAULT_KEYWORDS,
                          comment_tags=COMMENT_TAGS):
    """ We use Babel's exctract_from_dir() to pull out our gettext
    strings.  In the tests, I don't have a directory of files, I have StringIO
    objects.  So, we fake the original function with this one."""

    for lineno, message, comments in extract(method, fileobj, keywords,
            comment_tags, options):

        yield filename, lineno, message, comments
