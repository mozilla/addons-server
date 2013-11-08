import os
import StringIO

from django.conf import settings

from jinja2 import Environment, FileSystemLoader
from rest_framework.compat import etree, six
from rest_framework.exceptions import ParseError
from rest_framework.parsers import XMLParser

from amo.helpers import strip_controls
from mkt.constants import ratingsbodies


root = os.path.join(settings.ROOT, 'lib', 'iarc')
env = Environment(loader=FileSystemLoader(os.path.join(root, 'templates')))
env.finalize = lambda x: strip_controls(x)


def render_xml(template, context):
    """
    Renders an XML template given a dict of the context.

    This also strips control characters before encoding.

    """
    # All XML passed requires a password. Let's add it to the context.
    context['password'] = settings.IARC_PASSWORD

    template = env.get_template(template)
    return template.render(**context)


# Custom XML processor for IARC whack XML that defines all content in XML
# attributes with no tag content and all tags are named the same. This builds a
# dict using the "NAME" and "VALUE" attributes.
class IARC_XML_Parser(XMLParser):

    # TODO: Remove this `parse` method once this PR is merged and released:
    # https://github.com/tomchristie/django-rest-framework/pull/1211
    def parse(self, stream, media_type=None, parser_context=None):
        """
        Parses the incoming bytestream as XML and returns the resulting data.
        """
        assert etree, 'XMLParser requires defusedxml to be installed'

        parser_context = parser_context or {}
        encoding = parser_context.get('encoding', settings.DEFAULT_CHARSET)
        parser = etree.DefusedXMLParser(encoding=encoding)
        try:
            tree = etree.parse(stream, parser=parser, forbid_dtd=True)
        except (etree.ParseError, ValueError) as exc:
            raise ParseError('XML parse error - %s' % six.text_type(exc))
        data = self._xml_convert(tree.getroot())

        # Process ratings and descriptors.
        data = self._process_ratings_and_descriptors(data)

        return data

    def parse_string(self, string):
        # WARNING: Ugly hack.
        #
        # IARC XML is utf-8 encoded yet the XML has a utf-16 header. Python
        # correctly reports the encoding mismatch and raises an error. So we
        # replace it here to make things work.
        string = string.replace('encoding="utf-16"', 'encoding="utf-8"')
        return self.parse(StringIO.StringIO(string))

    def _xml_convert(self, element):
        """
        Convert the xml `element` into the corresponding Python object.
        """
        children = list(element)

        if len(children) == 0:
            return self._type_convert(element.get('VALUE'))
        else:
            data = {}
            for child in children:
                data[child.get('NAME', child.tag)] = self._xml_convert(child)

        return data

    def _process_ratings_and_descriptors(self, data):
        """
        Looks for keys starting with 'rating_' or 'descriptors_' and trades
        them for a 'ratings' and 'descriptors' dictionary.

        """
        d = {}  # New data object we'll return.
        ratings = {}
        descriptors = {}

        for k, v in data['ROW'].items():
            if k.startswith('rating_'):
                rating_body = k.split('_')[-1]
                # Get ratings body constants.
                rb_key = RATINGS_BODY_MAPPING.get(
                    rating_body, ratingsbodies.GENERIC)
                rb_val = RATINGS_MAPPING[rb_key].get(
                    v, RATINGS_MAPPING[rb_key]['default'])
                ratings[rb_key] = rb_val
            elif k.startswith('descriptors_'):
                # TODO: Convert to ratings descriptor classes.
                rating_body = k.split('_')[-1]
                descriptors[rating_body] = v
            else:
                d[k] = v

        if ratings:
            d['ratings'] = ratings
        if descriptors:
            d['descriptors'] = descriptors

        return d


# These mappings are required to convert the IARC response strings, like "ESRB"
# to the ratings body constants in mkt/constants/ratingsbodies. Likewise for
# the descriptors.
RATINGS_BODY_MAPPING = {
    'CLASSIND': ratingsbodies.CLASSIND,
    'ESRB': ratingsbodies.ESRB,
    'Generic': ratingsbodies.GENERIC,
    'PEGI': ratingsbodies.PEGI,
    'USK': ratingsbodies.USK,
    'default': ratingsbodies.GENERIC,
}

RATINGS_MAPPING = {
    ratingsbodies.CLASSIND: {
        'Livre': ratingsbodies.CLASSIND_L,
        '10+': ratingsbodies.CLASSIND_10,
        '12+': ratingsbodies.CLASSIND_12,
        '14+': ratingsbodies.CLASSIND_14,
        '16+': ratingsbodies.CLASSIND_16,
        '18+': ratingsbodies.CLASSIND_18,
        'default': ratingsbodies.CLASSIND_L,
    },
    ratingsbodies.ESRB: {
        'Everyone': ratingsbodies.ESRB_E,
        'Everyone 10+': ratingsbodies.ESRB_10,
        'Teen': ratingsbodies.ESRB_T,
        'Mature 17+': ratingsbodies.ESRB_M,
        'Adults Only': ratingsbodies.ESRB_A,
        'default': ratingsbodies.ESRB_E,
    },
    ratingsbodies.GENERIC: {
        '3+': ratingsbodies.GENERIC_3,
        '7+': ratingsbodies.GENERIC_7,
        '12+': ratingsbodies.GENERIC_12,
        '16+': ratingsbodies.GENERIC_16,
        '18+': ratingsbodies.GENERIC_18,
        'default': ratingsbodies.GENERIC_3,
    },
    # TODO: Fix these to match?
    ratingsbodies.PEGI: {
        '3+': ratingsbodies.PEGI_3,
        '10+': ratingsbodies.PEGI_7,
        '13+': ratingsbodies.PEGI_12,
        '17+': ratingsbodies.PEGI_16,
        '18+': ratingsbodies.PEGI_18,
        'default': ratingsbodies.PEGI_3,
    },
    ratingsbodies.USK: {
        '0+': ratingsbodies.USK_0,
        '6+': ratingsbodies.USK_6,
        '12+': ratingsbodies.USK_12,
        '16+': ratingsbodies.USK_16,
        '18+': ratingsbodies.USK_18,
        'default': ratingsbodies.USK_0,
    },
}
