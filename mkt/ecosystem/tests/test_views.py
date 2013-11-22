import basket
import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from amo.urlresolvers import reverse


VIEW_PAGES = (
    'build_app_generator', 'build_dev_tools', 'build_tools', 'design_ui',
    'dev_phone', 'partners', 'publish_deploy', 'support',
)

REDIRECT_PAGES = (
    'build_apps_offline', 'build_ffos', 'build_game_apps', 'build_intro',
    'build_manifests', 'build_mobile_developers', 'build_quick',
    'build_reference', 'build_web_developers', 'design_concept',
    'design_fundamentals', 'design_patterns', 'ffos_guideline',
    'publish_hosted', 'publish_packaged', 'publish_review', 'publish_submit',
    'responsive_design', 'firefox_os_simulator', 'build_payments',
)


class TestLanding(amo.tests.TestCase):

    def setUp(self):
        self.url = reverse('ecosystem.landing')

    def test_legacy_redirect(self):
        r = self.client.get('/ecosystem/')
        self.assert3xx(r, '/developers/', 301)

    def test_tutorials_default(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/landing.html')

    @mock.patch('basket.subscribe')
    def test_newsletter_form_valid(self, subscribe_mock):
        d = {'email': 'a@b.cd', 'email_format': 'T', 'privacy': True,
             'country': 'us'}
        r = self.client.post(self.url, d)
        self.assert3xx(r, reverse('ecosystem.landing'))
        assert subscribe_mock.called

    @mock.patch('basket.subscribe')
    def test_newsletter_form_invalid(self, subscribe_mock):
        d = {'email': '', 'email_format': 'T', 'privacy': True,
             'country': 'us'}
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'newsletter_form', 'email',
                             [u'Please enter a valid email address.'])
        assert not subscribe_mock.called

    @mock.patch('basket.subscribe')
    def test_newsletter_form_exception(self, subscribe_mock):
        subscribe_mock.side_effect = basket.BasketException
        d = {'email': 'a@b.cd', 'email_format': 'T', 'privacy': True,
             'country': 'us'}
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.notification-box.error h2').text(),
            'We apologize, but an error occurred in our '
            'system. Please try again later.')
        assert subscribe_mock.called


class TestDevHub(amo.tests.TestCase):

    def test_content_pages(self):
        for page in VIEW_PAGES:
            r = self.client.get(reverse('ecosystem.%s' % page))
            eq_(r.status_code, 200, '%s: status %s' % (page, r.status_code))
            self.assertTemplateUsed(r, 'ecosystem/%s.html' % page)

    def test_redirect_pages(self):
        for page in REDIRECT_PAGES:
            r = self.client.get(reverse('ecosystem.%s' % page))
            eq_(r.status_code, 301, '%s: status %s' % (page, r.status_code))

    def test_valid_reference_app(self):
        r = self.client.get(reverse('ecosystem.apps_documentation',
                            args=['face_value']))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/reference_apps/face_value.html')

    def test_invalid_reference_app(self):
        r = self.client.get(reverse('ecosystem.apps_documentation',
                            args=['face_value_invalid']))
        eq_(r.status_code, 404)
