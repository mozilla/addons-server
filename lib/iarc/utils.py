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
    context['company'] = settings.IARC_COMPANY
    context['platform'] = settings.IARC_PLATFORM

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

        # Process ratings, descriptors, interactives.
        data = self._process_ratings_and_descriptors(data)
        data = self._process_interactive_elements(data)

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
            # Get ratings body constant.
            ratings_body = RATINGS_BODY_MAPPING.get(
                k.split('_')[-1], ratingsbodies.GENERIC)

            if k.startswith('rating_'):
                ratings[ratings_body] = RATINGS_MAPPING[ratings_body].get(
                    v, RATINGS_MAPPING[ratings_body]['default'])
            elif k.startswith('descriptors_'):
                native_descs = filter(None, [s.strip() for s in v.split(',')])
                descriptors[ratings_body] = filter(None, [
                    DESC_MAPPING[ratings_body].get(desc)
                    for desc in native_descs])
            else:
                d[k] = v

        if ratings:
            d['ratings'] = ratings
        if descriptors:
            d['descriptors'] = descriptors

        return d

    def _process_interactive_elements(self, data):
        """Split and normalize the 'interactive_elements' key into a list."""
        data['interactives'] = []
        if not data.get('interactive_elements'):
            return data

        data['interactives'] = filter(
            None, [s.strip().lower().replace(' ', '_') for s in
                   data['interactive_elements'].split(',')])
        return data


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

DESC_MAPPING = {
    # All values will be capitalized and prepended with '%s_' % RATINGS_BODY in
    # a loop.
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
        u'Use of Alcohol and Tobacco': 'alcohol_tobacco_ref',
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
            body.name, desc_slug).lower()
