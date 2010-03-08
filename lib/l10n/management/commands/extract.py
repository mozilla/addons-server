import os
from manage import settings
from optparse import make_option
from subprocess import Popen
from settings import JINJA_CONFIG

from django.core.management.base import BaseCommand

from jinja2 import ext
from babel.messages.extract import (DEFAULT_KEYWORDS, extract_from_dir,
                                    extract_python)
from translate.storage import po

from l10n import strip_whitespace, add_context, split_context

DEFAULT_DOMAIN = 'all'

DOMAIN_METHODS = {
    'messages': [
        ('apps/**.py',
            'l10n.management.commands.extract.extract_amo_python'),
        ('**/templates/**.html',
            'l10n.management.commands.extract.extract_amo_template'),
    ],
    'lhtml': [
        ('**/templates/**.lhtml',
            'l10n.management.commands.extract.extract_amo_template'),
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

OPTIONS_MAP = {
    '**.*': {'extensions': ",".join(JINJA_CONFIG()['extensions'])},
}

COMMENT_TAGS = ['L10n:']


def tweak_message(message):
    """We piggyback on jinja2's babel_extract() (really, Babel's extract_*
    functions) but they don't support some things we need so this function will
    tweak the message.  Specifically:

        1) We strip whitespace from the msgid.  Jinja2 will only strip
            whitespace from the ends of a string so linebreaks show up in
            your .po files still.

        2) Babel doesn't support context (msgctxt).  We hack that in ourselves
            here.
    """
    if isinstance(message, basestring):
        message = strip_whitespace(message)
    elif isinstance(message, tuple):
        # A tuple of 2 has context, 3 is plural, 4 is plural with context
        if len(message) == 2:
            message = add_context(message[1], message[0])
        elif len(message) == 3:
            singular, plural, num = message
            message = (strip_whitespace(singular),
                       strip_whitespace(plural),
                       num)
        elif len(message) == 4:
            singular, plural, num, ctxt = message
            message = (add_context(ctxt, strip_whitespace(singular)),
                       add_context(ctxt, strip_whitespace(plural)),
                       num)
    return message


def extract_amo_python(fileobj, keywords, comment_tags, options):
    for lineno, funcname, message, comments in \
            list(extract_python(fileobj, keywords, comment_tags, options)):

        message = tweak_message(message)

        yield lineno, funcname, message, comments


def extract_amo_template(fileobj, keywords, comment_tags, options):
    for lineno, funcname, message, comments in \
            list(ext.babel_extract(fileobj, keywords, comment_tags, options)):

        message = tweak_message(message)

        yield lineno, funcname, message, comments


def create_pounit(filename, lineno, message, comments):
    unit = po.pounit(encoding="UTF-8")
    if isinstance(message, tuple):
        _, s = split_context(message[0])
        c, p = split_context(message[1])
        unit.setsource([s, p])
        # Workaround for http://bugs.locamotion.org/show_bug.cgi?id=1385
        unit.target = [u"", u""]
    else:
        c, m = split_context(message)
        unit.setsource(m)
    if c:
        unit.msgctxt = ['"%s"' % c]
    if comments:
        for comment in comments:
            unit.addnote(comment, "developer")

    unit.addlocation("%s:%s" % (filename, lineno))
    return unit


def create_pofile_from_babel(extracted):
    catalog = po.pofile(inputfile="")
    for filename, lineno, message, comments in extracted:
        unit = create_pounit(filename, lineno, message, comments)
        catalog.addunit(unit)
    catalog.removeduplicates()
    return catalog


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('--domain', '-d', default=DEFAULT_DOMAIN, dest='domain',
                    help='The domain of the message files.  If "all" '
                         'everything will be extracted and combined into '
                         'z-keys.pot. (default: %s).' % DEFAULT_DOMAIN),
            )

    def handle(self, *args, **options):
        domains = options.get('domain')

        if domains == "all":
            domains = DOMAIN_METHODS.keys()
        else:
            domains = [domains]

        root = settings.ROOT

        def callback(filename, method, options):
            if method != 'ignore':
                print "  %s" % filename

        for domain in domains:

            print "Extracting all strings in domain %s..." % (domain)

            methods = DOMAIN_METHODS[domain]
            extracted = extract_from_dir(root,
                                         method_map=methods,
                                         keywords=DEFAULT_KEYWORDS,
                                         comment_tags=COMMENT_TAGS,
                                         callback=callback,
                                         options_map=OPTIONS_MAP,
                                         )
            catalog = create_pofile_from_babel(extracted)
            catalog.savefile(os.path.join(root, 'locale', 'z-%s.pot' % domain))

        if len(domains) > 1:
            print "Concatenating all domains..."
            pot_files = []
            for i in domains:
                pot_files.append(os.path.join(root, 'locale', 'z-%s.pot' % i))
            z_keys = open(os.path.join(root, 'locale', 'z-keys.pot'), 'w+t')
            z_keys.truncate()
            command = ["msgcat"] + pot_files
            p1 = Popen(command, stdout=z_keys)
            p1.communicate()
            z_keys.close()
            for i in domains:
                os.remove(os.path.join(root, 'locale', 'z-%s.pot' % i))

        print 'done'
