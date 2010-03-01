import jinja2
from jinja2.ext import InternationalizationExtension

from l10n import strip_whitespace


@jinja2.contextfunction
def _gettext_alias(context, string, *args, **kw):
    return context.resolve('gettext')(string, *args, **kw)


class MozInternationalizationExtension(InternationalizationExtension):
    """
    We override jinja2's _parse_block() to collapse whitespace so we can have
    linebreaks wherever we want, and hijack _() to take contexts.
    """

    def __init__(self, environment):
        super(MozInternationalizationExtension, self).__init__(environment)
        environment.globals['_'] = _gettext_alias

    def _parse_block(self, parser, allow_pluralize):
        parse_block = InternationalizationExtension._parse_block
        ref, buffer = parse_block(self, parser, allow_pluralize)
        return ref, strip_whitespace(buffer)

i18n = MozInternationalizationExtension
