from django.conf import settings

import basket
import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from amo.urlresolvers import reverse
from mkt.ecosystem.models import MdnCache


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

    @mock.patch.object(settings, 'MDN_LAZY_REFRESH', True)
    @mock.patch('mkt.ecosystem.views.refresh_mdn_cache')
    def test_tutorials_refresh(self, mock_):
        self.client.get(self.url)
        assert not mock_.called

        self.client.get(self.url, {'refresh': '1'})
        assert mock_.called

    @mock.patch.object(settings, 'MDN_LAZY_REFRESH', False)
    @mock.patch('mkt.ecosystem.views.refresh_mdn_cache')
    def test_tutorials_refresh_disabled(self, mock_):
        self.client.get(self.url)
        assert not mock_.called

        self.client.get(self.url, {'refresh': '1'})
        assert not mock_.called

    @mock.patch('basket.subscribe')
    def test_newsletter_form_valid(self, subscribe_mock):
        d = {'email': 'a@b.cd', 'privacy': True}
        r = self.client.post(self.url, d)
        self.assert3xx(r, reverse('ecosystem.landing'))
        assert subscribe_mock.called

    @mock.patch('basket.subscribe')
    def test_newsletter_form_invalid(self, subscribe_mock):
        d = {'email': '', 'privacy': True}
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'newsletter_form', 'email',
                             [u'Please enter a valid email address.'])
        assert not subscribe_mock.called

    @mock.patch('basket.subscribe')
    def test_newsletter_form_exception(self, subscribe_mock):
        subscribe_mock.side_effect = basket.BasketException
        d = {'email': 'a@b.cd', 'privacy': True}
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.notification-box.error h2').text(),
                          'We apologize, but an error occurred in our '
                          'system. Please try again later.')
        assert subscribe_mock.called


class TestDevHub(amo.tests.TestCase):

    def test_support(self):
        r = self.client.get(reverse('ecosystem.support'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/support.html')

    def test_partners(self):
        r = self.client.get(reverse('ecosystem.partners'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/partners.html')

    def test_valid_reference_app(self):
        r = self.client.get(reverse('ecosystem.apps_documentation',
                            args=['face_value']))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/reference_apps/face_value.html')

    def test_invalid_reference_app(self):
        r = self.client.get(reverse('ecosystem.apps_documentation',
                            args=['face_value_invalid']))
        eq_(r.status_code, 404)


class TestMdnDocumentation(amo.tests.TestCase):
    fixtures = ['ecosystem/mdncache-item']

    def setUp(self):
        self.url = reverse('ecosystem.documentation')

    def test_mdn_content_default(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/documentation.html')

    def test_mdn_content_design(self):
        r = self.client.get(reverse('ecosystem.documentation',
                            args=['principles']))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/documentation.html')

    def test_mdn_content_explicit(self):
        r = self.client.get(self.url + 'old')
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/documentation.html')

    def test_mdn_content_unknown(self):
        r = self.client.get(self.url + 'pizza')
        eq_(r.status_code, 404)
        self.assertTemplateUsed(r, 'site/404.html')

    def test_mdn_article_with_missing_locale(self):
        r = self.client.get(self.url, HTTP_ACCEPT_LANGUAGE='pt-BR')
        eq_(r.status_code, 200)
        eq_(pq(r.content)('html').attr('lang'), 'pt-BR')

    def test_mdn_content_content(self):
        a = MdnCache.objects.filter(name='html5', locale='en-US')[0]
        a.content = '<strong>pizza</strong>'
        a.save()

        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('strong').text(), 'pizza')
