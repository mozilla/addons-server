# -*- coding: utf8 -*-
from xml.parsers import expat

import mock
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from files.models import File
from files.utils import SafeUnzip, RDF, watermark
from users.models import UserProfile
from versions.models import Version


class TestWatermark(amo.tests.TestCase, amo.tests.AMOPaths):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.version = Version.objects.create(addon=self.addon)
        self.file = File.objects.create(version=self.version,
                                        filename=self.xpi_path('firefm'))
        self.user = UserProfile.objects.get(pk=999)

    def get_rdf(self, tmp):
        unzip = SafeUnzip(tmp)
        unzip.is_valid()
        return RDF(unzip.extract_path('install.rdf'))

    def get_updateURL(self, rdf):
        return (rdf.dom.getElementsByTagName('em:updateURL')[0]
                       .firstChild.nodeValue)

    @mock.patch('files.utils.SafeUnzip.extract_path')
    def get_extract(self, data, extract_path):
        extract_path.return_value = data
        return watermark(self.file, self.user)

    def test_watermark(self):
        tmp = watermark(self.file, self.user)
        eq_(self.user.email in self.get_updateURL(self.get_rdf(tmp)), True)

    def test_watermark_unicode(self):
        self.user.email = u'Strauß@Magyarország.com'
        tmp = watermark(self.file, self.user)
        eq_(self.user.email in self.get_updateURL(self.get_rdf(tmp)), True)

    def test_watermark_no_data(self):
        self.assertRaises(expat.ExpatError, self.get_extract, '')

    def test_watermark_no_description(self):
        self.assertRaises(IndexError, self.get_extract, """
<RDF xmlns="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns:em="http://www.mozilla.org/2004/em-rdf#">
</RDF>""")

    def test_watermark_overwrites(self):
        tmp = self.get_extract("""
<RDF xmlns="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  xmlns:em="http://www.mozilla.org/2004/em-rdf#">

  <Description about="urn:mozilla:install-manifest">
    <em:updateURL>http://my.other.site/</em:updateURL>
  </Description>
</RDF>""")
        eq_(self.user.email in self.get_updateURL(self.get_rdf(tmp)), True)

    def test_watermark_overwrites_multiple(self):
        tmp = self.get_extract("""
<RDF xmlns="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  xmlns:em="http://www.mozilla.org/2004/em-rdf#">

  <Description about="urn:mozilla:install-manifest">
    <em:updateURL>http://my.other.site/</em:updateURL>
    <em:updateURL>http://my.other.other.site/</em:updateURL>
  </Description>
</RDF>""")
        eq_(self.user.email in self.get_updateURL(self.get_rdf(tmp)), True)
        # one close and one open
        eq_(str(self.get_rdf(tmp)).count('updateURL'), 2)
