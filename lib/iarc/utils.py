import os
import StringIO

from django.conf import settings

from jinja2 import Environment, FileSystemLoader
from rest_framework.compat import etree, six
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser, XMLParser

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
    context['company'] = settings.IARC_COMPANY
    context['platform'] = settings.IARC_PLATFORM

    template = env.get_template(template)
    return template.render(**context)


class IARC_Parser(object):
    """
    Base class for IARC XML and JSON parsers.
    """

    def _process_iarc_items(self, data):
        """
        Looks for IARC keys ('interactive_elements' or keys starting with
        'rating_' or 'descriptors_') and trades them for a 'ratings' dictionary
        or descriptor and interactive lists.

        """
        rows = []  # New data object we'll return.

        for row in data:
            d = {}
            ratings = {}
            descriptors = []
            interactives = []

            for k, v in row.items():
                # Get ratings body constant.
                ratings_body = RATINGS_BODY_MAPPING.get(
                    k.split('_')[-1].lower(), ratingsbodies.GENERIC)

                if k == 'rating_system':
                    # This key is used in the Get_Rating_Changes API.
                    d[k] = RATINGS_BODY_MAPPING.get(v.lower(),
                                                    ratingsbodies.GENERIC)
                elif k == 'interactive_elements':
                    interactives = [INTERACTIVES_MAPPING[s] for s in
                                    filter(None, [s.strip()
                                                  for s in v.split(',')])]
                elif k.startswith('rating_'):
                    ratings[ratings_body] = RATINGS_MAPPING[ratings_body].get(
                        v, RATINGS_MAPPING[ratings_body]['default'])
                elif k.startswith('descriptors_'):
                    native_descs = filter(None,
                                          [s.strip() for s in v.split(',')])
                    descriptors.extend(
                        filter(None, [DESC_MAPPING[ratings_body].get(desc)
                                      for desc in native_descs]))
                else:
                    d[k] = v

            if ratings:
                d['ratings'] = ratings
            if descriptors:
                d['descriptors'] = descriptors
            if interactives:
                d['interactives'] = interactives

            rows.append(d)

        return rows


class IARC_XML_Parser(XMLParser, IARC_Parser):
    """
    Custom XML processor for IARC whack XML that defines all content in XML
    attributes with no tag content and all tags are named the same. This builds
    a dict using the "NAME" and "VALUE" attributes.
    """

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

        # Process ratings, descriptors, interactives.
        data = self._process_iarc_items(data)

        # If it's a list, it had one or more "ROW" tags.
        if isinstance(data, list):
            data = {'rows': data}

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
            if children[0].tag == 'ROW':
                data = []
                for child in children:
                    data.append(self._xml_convert(child))
            else:
                data = {}
                for child in children:
                    data[child.get('NAME',
                                   child.tag)] = self._xml_convert(child)

        return data


class IARC_JSON_Parser(JSONParser, IARC_Parser):
    """
    JSON Parser to handle IARC's JSON format.
    """
    def parse(self, stream, media_type=None, parser_context=None):
        data = super(IARC_JSON_Parser, self).parse(stream, media_type,
                                                   parser_context)
        data = self._convert(data)
        data = self._process_iarc_items(data)

        return data

    def _convert(self, data):
        """
        Converts JSON that looks like::

            {
                "NAME": "token",
                "TYPE": "string",
                "VALUE": "AB12CD3"
            }

        Into something more normal that looks like this::

            {
                "token": "AB12CD3"
            }

        """
        d = {}
        for f in data['ROW']['FIELD']:
            d[f['NAME']] = f['VALUE']

        # Return a list to match the parsed XML.
        return [d]


# These mappings are required to convert the IARC response strings, like "ESRB"
# to the ratings body constants in mkt/constants/ratingsbodies. Likewise for
# the descriptors.
RATINGS_BODY_MAPPING = {
    'classind': ratingsbodies.CLASSIND,
    'esrb': ratingsbodies.ESRB,
    'generic': ratingsbodies.GENERIC,
    'pegi': ratingsbodies.PEGI,
    'usk': ratingsbodies.USK,
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


DESC_MAPPING = {
    # All values will be prepended with 'has_%s_' % RATINGS_BODY later.
    ratingsbodies.CLASSIND: {
        u'Viol\xEAncia': 'violence',
        u'Viol\xEAncia Extrema': 'violence_extreme',
        u'Cont\xE9udo Sexual': 'sex_content',
        u'Nudez': 'nudity',
        u'Sexo': 'sex_content',
        u'Sexo Expl\xEDcito': 'sex_explicit',
        u'Drogas': 'drugs',
        u'Drogas L\xEDcitas': 'drugs_legal',
        u'Drogas Il\xEDcitas': 'drugs_illegal',
        u'Linguagem Impr\xF3pria': 'lang',
        u'Atos Crim\xEDnosos': 'criminal_acts',
        u'Conte\xFAdo Impactante': 'shocking',
        u'N\xE3o h\xE1 inadequa\xE7\xF5es': 'no_descs',
    },

    ratingsbodies.ESRB: {
        u'Alcohol Reference': 'alcohol',
        u'Blood': 'blood',
        u'Blood and Gore': 'blood_gore',
        u'Crude Humor': 'crude_humor',
        u'Drug Reference': 'drug_ref',
        u'Fantasy Violence': 'fantasy_violence',
        u'Intense Violence': 'intense_violence',
        u'Language': 'lang',
        u'Mild Blood': 'mild_blood',
        u'Mild Fantasy Violence': 'mild_fantasy_violence',
        u'Mild Language': 'mild_lang',
        u'Mild Violence': 'mild_violence',
        u'Nudity': 'nudity',
        u'Partial Nudity': 'partial_nudity',
        u'Real Gambling': 'real_gambling',
        u'Sexual Content': 'sex_content',
        u'Sexual Themes': 'sex_themes',
        u'Simulated Gambling': 'sim_gambling',
        u'Strong Language': 'strong_lang',
        u'Strong Sexual Content': 'strong_sex_content',
        u'Suggestive Themes': 'suggestive',
        u'Tobacco Reference': 'tobacco_ref',
        u'Use of Alcohol': 'alcohol_use',
        u'Use of Drugs': 'drug_use',
        u'Use of Tobacco': 'tobacco_use',
        u'Violence': 'violence',
        u'Violent References': 'violence_ref',
        u'No Descriptors': 'no_descs',
        u'Comic Mischief ': 'comic_mischief',
        u'Alcohol and Tobacco Reference': 'alcohol_tobacco_ref',
        u'Drug and Alcohol Reference': 'drug_alcohol_ref',
        u'Use of Alcohol and Tobacco': 'alcohol_tobacco_use',
        u'Use of Drug and Alcohol': 'drug_alcohol_use',
        u'Drug and Tobacco Reference': 'drug_tobacco_ref',
        u'Drug, Alcohol and Tobacco Reference': 'drug_alcohol_tobacco_ref',
        u'Use of Drug and Tobacco': 'drug_tobacco_use',
        u'Use of Drug, Alcohol and Tobacco': 'drug_alcohol_tobacco_use',
        u'Scary Themes': 'scary',
        u'Hate Speech': 'hate_speech',
        u'Crime': 'crime',
        u'Criminal Instruction': 'crime_instruct',
    },

    ratingsbodies.GENERIC: {
        u'Alcohol Reference': 'alcohol_ref',
        u'Blood': 'blood',
        u'Blood and Gore': 'blood_gore',
        u'Crude Humor': 'crude_humor',
        u'Drug Reference': 'drug_ref',
        u'Fantasy Violence': 'fantasy_violence',
        u'Intense Violence': 'intense_violence',
        u'Language': 'lang',
        u'Mild Blood': 'mild_blood',
        u'Mild Fantasy Violence': 'mild_fantasy_violence',
        u'Mild Language': 'mild_lang',
        u'Mild Violence': 'mild_violence',
        u'Nudity': 'nudity',
        u'Partial Nudity': 'partial_nudity',
        u'Real Gambling': 'real_gambling',
        u'Sexual Content': 'sex_content',
        u'Sexual Themes': 'sex_themes',
        u'Simulated Gambling': 'sim_gambling',
        u'Strong Language': 'strong_lang',
        u'Strong Sexual Content': 'strong_sex_content',
        u'Suggestive Themes': 'suggestive',
    },

    ratingsbodies.PEGI: {
        u'Violence': 'violence',
        u'Language': 'lang',
        u'Fear': 'scary',
        u'Sex': 'sex_content',
        u'Drugs': 'drugs',
        u'Discrimination': 'discrimination',
        u'Gambling': 'gambling',
        u'Online': 'online',
        u'No Descriptors': 'no_descs',
    },

    ratingsbodies.USK: {
        u'No Descriptors': 'no_descs',
        u'\xC4ngstigende Inhalte': 'scary',
        u'Erotik/Sexuelle Inhalte': 'sex_content',
        u'Explizite Sprache': 'lang',
        u'Diskriminierung': 'discrimination',
        u'Drogen': 'drugs',
        u'Gewalt': 'violence',
    },
}


for body, mappings in DESC_MAPPING.items():
    for native_desc, desc_slug in mappings.items():
        DESC_MAPPING[body][native_desc] = 'has_{0}_{1}'.format(
            body.iarc_name, desc_slug).lower()

# Change {body: {'key': 'val'}} to {'val': 'key'}.
REVERSE_DESC_MAPPING_BY_BODY = (
    dict([(unicode(v), unicode(k)) for k, v in body_mapping.iteritems()])
    for body, body_mapping in DESC_MAPPING.iteritems())
REVERSE_DESC_MAPPING = {}
for mapping in REVERSE_DESC_MAPPING_BY_BODY:
    REVERSE_DESC_MAPPING.update(mapping)


INTERACTIVES_MAPPING = {
    'Users Interact': 'has_users_interact',
    'Shares Info': 'has_shares_info',
    'Shares Location': 'has_shares_location',
    'Digital Purchases': 'has_digital_purchases',
    'Social Networking': 'has_social_networking',
    'Digital Content Portal': 'has_digital_content_portal',
}

REVERSE_INTERACTIVES_MAPPING = dict(
    (v, k) for k, v in INTERACTIVES_MAPPING.iteritems())
