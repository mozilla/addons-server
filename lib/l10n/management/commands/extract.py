import os
from manage import settings
from optparse import make_option

from babel.messages import Catalog
from babel.messages.extract import extract_from_dir
from babel.messages.pofile import write_po

from django.core.management.base import BaseCommand

from jinja2 import ext

from l10n import strip_whitespace

DEFAULT_DOMAIN = 'messages'

KEYWORDS = {
    '_': None,
    'gettext': None,
    'ngettext': (1, 2),
}

DOMAIN_METHODS = {
    DEFAULT_DOMAIN: [
        ('apps/**.py', 'python'),
        ('**/templates/**.html',
            'lib.l10n.management.commands.extract.extract_amo_template'),
    ],
    'lhtml': [
        ('**/templates/**.lhtml',
            'lib.l10n.management.commands.extract.extract_amo_template'),
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
    returned.  Specifically, we strip whitespace from the msgid.  Jinja2 will
k   only strip whitespace from the ends of a string and then only if you ask
    it which means linebreaks show up in your .po files.

    See babel_extract() for more details.
    """

    options['extensions'] = 'caching.ext.cache'
    for lineno, funcname, message, comments in \
            list(ext.babel_extract(fileobj, keywords, comment_tags, options)):

        if isinstance(message, basestring):
            message = strip_whitespace(message)
        elif isinstance(message, list):
            message = [strip_whitespace(x) for x in message if x is not None]
        elif isinstance(message, tuple):
            # Plural form
            message = (strip_whitespace(message[0]),
                      strip_whitespace(message[1]),
                      message[2])

        yield lineno, funcname, message, comments


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('--domain', '-d', default=DEFAULT_DOMAIN, dest='domain',
                    help='The domain of the message files '
                         '(default: %s).' % DEFAULT_DOMAIN),
            )

    def handle(self, *args, **options):
        domain = options.get('domain')

        root = settings.ROOT
        print "Extracting all strings for in domain %s..." % (domain)

        catalog = Catalog(
                    domain=domain,
                    project="addons.mozilla.org",
                    copyright_holder="Mozilla Corporation",
                    msgid_bugs_address="dev-l10n-web@lists.mozilla.org",
                    charset='utf-8')

        def callback(filename, method, options):
            if method != 'ignore':
                print "  %s" % filename

        methods = DOMAIN_METHODS[domain]
        extracted = extract_from_dir(root,
                                     method_map=methods,
                                     keywords=KEYWORDS,
                                     comment_tags=COMMENT_TAGS,
                                     callback=callback)

        for filename, lineno, message, comments in extracted:
            catalog.add(message, None, [(filename, lineno)],
                        auto_comments=comments)

        f = file(os.path.join(root, 'locale', 'z-%s.pot' % domain), 'w')

        try:
            write_po(f, catalog, width=79)
        finally:
            f.close()

        print 'done'
