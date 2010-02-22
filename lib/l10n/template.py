from jinja2.ext import InternationalizationExtension

from l10n import strip_whitespace


class MozInternationalizationExtension(InternationalizationExtension):
    """ We override jinja2's _parse_block() to collapse whitespace so
        we can have linebreaks wherever we want.
    """
    def _parse_block(self, parser, allow_pluralize):
        parse_block = InternationalizationExtension._parse_block
        ref, buffer = parse_block(self, parser, allow_pluralize)
        return ref, strip_whitespace(buffer)

i18n = MozInternationalizationExtension
