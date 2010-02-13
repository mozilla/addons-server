#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Extract python and AMO template files into a .pot.  Some ideas stolen from
http://dev.pocoo.org/projects/zine/browser/scripts/extract-messages
"""
from optparse import OptionParser
from os import path

from babel.messages import Catalog
from babel.messages.extract import extract_from_dir
from babel.messages.pofile import write_po
from jinja2 import ext

DEFAULT_DOMAIN = 'messages'

KEYWORDS = {
    '_': None,
    'gettext': None,
    'ngettext': (1, 2),
}

DOMAIN_METHODS = {
    DEFAULT_DOMAIN: [
        ('apps/**.py', 'python'),
        ('**/templates/**.html', 'extract-po:extract_amo_template'),
    ],
    'lhtml': [
        ('**/templates/**.lhtml', 'extract-po:extract_amo_template'),
    ],
    'javascript': [
        # We can't say **.js because that would dive into mochikit and timeplot
        # and all the other baggage we're carrying.  Timeplot, in particular,
        # crashes the extractor with bad unicode data.
        ('media/js/*.js', 'javascript'),
        ('media/js/amo2009/**.js', 'javascript'),
        ('media/js/zamboni/**.js', 'javascript'),
    ],
}

COMMENT_TAGS = ['L10n:']


def extract_amo_template(fileobj, keywords, comment_tags, options):
    """ Extract localizable strings from a template (.html) file.  We piggyback
    on jinja2's babel_extract() function but tweak the output before it's
    returned.  Specifically, we strip whitespace from both ends of the msgid.
    Jinja2 doesn't strip whitespace unless you specifically request it by
    using dashes in your {% trans %}.

    See babel_extract() for more details.

    One thing missing from template extraction is developer comments for
    localizers.  babel_extract() does not support comments. Bug at
    http://dev.pocoo.org/projects/jinja/ticket/362
    """

    for lineno, funcname, message, comments in \
            list(ext.babel_extract(fileobj, keywords, comment_tags, options)):

        if isinstance(message, basestring):
            message = message.strip()
        elif isinstance(message, list):
            message = [x.strip() for x in message if x is not None]

        yield lineno, funcname, message, comments


def main():
    parser = OptionParser()
    parser.add_option('-d', '--domain', default=DEFAULT_DOMAIN,
                      help="Domain of the messages file. "
                           "(default: %s)" % DEFAULT_DOMAIN)
    options, args = parser.parse_args()

    domain = options.domain
    root = path.abspath(path.join(path.dirname(__file__), path.pardir))

    print "Extracting all strings for %s (%s)..." % (domain, root)

    catalog = Catalog(
                domain=domain,
                project="addons.mozilla.org",
                copyright_holder="Mozilla Corporation",
                msgid_bugs_address="dev-l10n-web@lists.mozilla.org",
                last_translator="AMO Team <dev-l10n-web@lists.mozilla.org>",
                language_team="AMO Team <dev-l10n-web@lists.mozilla.org>",
                charset='utf-8')

    def callback(filename, method, options):
        if method != 'ignore':
            print "  %s" % filename

    methods = DOMAIN_METHODS[domain]
    extracted = extract_from_dir(root, method_map=methods, keywords=KEYWORDS,
                                 comment_tags=COMMENT_TAGS, callback=callback)

    for filename, lineno, message, comments in extracted:
        catalog.add(message, None, [(filename, lineno)],
                    auto_comments=comments)

    f = file(path.join(root, 'locale', '%s.pot' % domain), 'w')

    try:
        write_po(f, catalog, width=79)
    finally:
        f.close()

    print 'done'


if __name__ == '__main__':
    main()
