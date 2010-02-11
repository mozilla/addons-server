from django.conf import settings

from test_utils import TestCase

import api


class APITest(TestCase):

    fixtures = ['base/addons']

    def test_redirection(self):
        """
        Test that /api/addon is redirected to /api/LATEST_API_VERSION/addon
        """
        response = self.client.get('/en-US/firefox/api/addon/12', follow=True)
        last_link = response.redirect_chain[-1]
        assert last_link[0].endswith('en-US/firefox/api/%.1f/addon/12' %
            api.CURRENT_VERSION)

    def test_forbidden_api(self):
        """
        APIs older than api.MIN_VERSION are deprecated, and we send a 403.
        We suggest people to use api.CURRENT_VERSION.
        """

        response = self.client.get('/en-US/firefox/api/0.9/addon/12')
        self.assertContains(response, 'The API version, %.1f, you are using '
            'is not valid.  Please upgrade to the current version %.1f '
            'API.' % (0.9, api.CURRENT_VERSION), status_code=403)

    def test_addon_detail_missing(self):
        """
        Check missing addons.
        """
        response = self.client.get('/en-US/firefox/api/%.1f/addon/999' %
            api.CURRENT_VERSION)

        self.assertContains(response, 'Add-on not found!', status_code=404)

    def test_addon_detail(self):
        """
        Test for expected strings in the XML.
        """
        response = self.client.get('/en-US/firefox/api/%.1f/addon/3615' %
                                   api.CURRENT_VERSION)

        self.assertContains(response, "<name>Delicious Bookmarks</name>")
        self.assertContains(response, """id="1">Extension</type>""")
        self.assertContains(response,
                """<guid>{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}</guid>""")
        self.assertContains(response, "<version>1.0.43</version>")
        self.assertContains(response, """<status id="4">Public</status>""")
        self.assertContains(response, "<author>carlsjr</author>")
        self.assertContains(response, "<summary>Best Addon Evar</summary>")
        self.assertContains(response,
                "<description>Delicious blah blah blah</description>")

        icon_url = settings.ADDON_ICON_URL % (3615, 1256144332)
        self.assertContains(response, icon_url + '</icon>')
        self.assertContains(response, "<application>")
        self.assertContains(response, "<name>Firefox</name>")
        self.assertContains(response, "<application_id>1</application_id>")
        self.assertContains(response, "<min_version>1</min_version>")
        self.assertContains(response, "<max_version>2</max_version>")
        self.assertContains(response, "<os>ALL</os>")
        self.assertContains(response, "<eula>None</eula>")
        self.assertContains(response, "/img/no-preview.png</thumbnail>")
        self.assertContains(response, "<rating>3</rating>")
        self.assertContains(response, "/en-US/firefox/addon/3615/?src=api</learnmore>")
        self.assertContains(response,
                """hash="sha256:5b5aaf7b38e332cc95d92ba759c01"""
                "c3076b53a840f6c16e01dc272eefcb29566")


