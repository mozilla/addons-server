from django.test.utils import override_settings

from nose.tools import eq_

import amo.tests

from lib.iarc.client import get_iarc_client
from lib.iarc.utils import IARC_XML_Parser, render_xml

from mkt.constants import ratingsbodies


class TestRenderAppInfo(amo.tests.TestCase):

    def setUp(self):
        self.template = 'get_app_info.xml'

    @override_settings(IARC_PASSWORD='s3kr3t')
    def test_render(self):
        xml = render_xml(self.template, {'submission_id': 100,
                                         'security_code': 'AB12CD3'})
        assert xml.startswith('<?xml version="1.0" encoding="utf-8"?>')
        assert '<FIELD NAME="password" VALUE="s3kr3t"' in xml
        assert '<FIELD NAME="submission_id" VALUE="100"' in xml
        assert '<FIELD NAME="security_code" VALUE="AB12CD3"' in xml
        # If these aren't specified in the context they aren't included.
        assert not '<FIELD NAME="title"' in xml
        assert not '<FIELD NAME="company"' in xml
        assert not '<FIELD NAME="platform"' in xml


class TestXMLParser(amo.tests.TestCase):

    def setUp(self):
        self.client = get_iarc_client('service')

    def test_app_info(self):
        xml = self.client.Get_App_Info()
        data = IARC_XML_Parser().parse_string(xml)

        eq_(data['submission_id'], 52)
        eq_(data['title'], 'twitter')
        eq_(data['company'], 'Mozilla')
        eq_(data['interactive_elements'],
            'Shares Info, Shares Location, Social Networking, Users Interact, ')
        eq_(data['storefront'], 'Mozilla')
        eq_(data['platform'], 'Firefox Browser,Firefox OS')

        # Test ratings get mapped to their appropriate rating classes.
        eq_(data['ratings'][ratingsbodies.ESRB], ratingsbodies.ESRB_M)
        eq_(data['ratings'][ratingsbodies.USK], ratingsbodies.USK_12)
        eq_(data['ratings'][ratingsbodies.CLASSIND], ratingsbodies.CLASSIND_14)
        eq_(data['ratings'][ratingsbodies.PEGI], ratingsbodies.PEGI_3)
        eq_(data['ratings'][ratingsbodies.GENERIC], ratingsbodies.GENERIC_16)

        # Test descriptors.
        eq_(data['descriptors'][ratingsbodies.GENERIC], ['has_generic_lang'])
        eq_(data['descriptors'][ratingsbodies.USK], ['has_usk_lang'])
        eq_(data['descriptors'][ratingsbodies.ESRB], [u'has_esrb_strong_lang'])
        self.assertSetEqual(
            data['descriptors'][ratingsbodies.CLASSIND],
            [u'has_classind_sex_content', u'has_classind_lang'])
        self.assertSetEqual(data['descriptors'][ratingsbodies.PEGI],
                            ['has_pegi_lang', 'has_pegi_online'])

        # Test interactives.
        self.assertSetEqual(data['interactives'],
                            ['shares_info', 'shares_location',
                             'social_networking', 'users_interact'])
