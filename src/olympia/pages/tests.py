from django.conf import settings

from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse


class TestPages(TestCase):

    def _check(self, url, status):
        resp = self.client.get(reverse(url))
        assert resp.status_code == status

    def test_status(self):
        pages = ['pages.about', 'pages.credits', 'pages.faq',
                 'pages.acr_firstrun', 'pages.dev_faq', 'pages.review_guide',
                 'pages.sunbird', 'pages.shield_study_2',
                 'pages.shield_study_3', 'pages.shield_study_4',
                 'pages.shield_study_5', 'pages.shield_study_6',
                 'pages.shield_study_7', 'pages.shield_study_8',
                 'pages.shield_study_9', 'pages.shield_study_10',
                 'pages.shield_study_11', 'pages.shield_study_12',
                 'pages.shield_study_13']
        for page in pages:
            self._check(page, 200)


class TestRedirects(TestCase):

    def _check(self, pages):
        for old, new in pages.iteritems():
            if new.startswith('http'):
                r = self.client.get(old)
                assert r['Location'] == new
            else:
                r = self.client.get(old, follow=True)
                self.assert3xx(r, new, 301)

    def test_app_pages(self):
        self._check({
            '/en-US/firefox/pages/compatibility_firstrun':
                reverse('pages.acr_firstrun'),
            '/en-US/firefox/pages/validation': settings.VALIDATION_FAQ_URL,
        })

    def test_nonapp_pages(self):
        self._check({
            '/en-US/pages/developer_faq': reverse('pages.dev_faq'),
            '/en-US/pages/review_guide': reverse('pages.review_guide'),
        })
        r = self.client.get('/en-US/firefox/pages/developer_agreement',
                            follow=False)
        self.assert3xx(r, reverse(
            'devhub.docs', args=['policies/agreement']), 301)
