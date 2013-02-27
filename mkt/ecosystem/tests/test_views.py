from django.conf import settings

import basket
import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from amo.urlresolvers import reverse


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

    def test_dev_phone(self):
        r = self.client.get(reverse('ecosystem.dev_phone'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/dev_phone.html')

    def test_valid_reference_app(self):
        r = self.client.get(reverse('ecosystem.apps_documentation',
                            args=['face_value']))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/reference_apps/face_value.html')

    def test_invalid_reference_app(self):
        r = self.client.get(reverse('ecosystem.apps_documentation',
                            args=['face_value_invalid']))
        eq_(r.status_code, 404)

    def test_design_concept(self):
        r = self.client.get(reverse('ecosystem.design_concept'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/design_concept.html')

    def test_design_fundamentals(self):
        r = self.client.get(reverse('ecosystem.design_fundamentals'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/design_fundamentals.html')

    def test_design_ui_guidelines(self):
        r = self.client.get(reverse('ecosystem.design_ui'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/design_ui.html')

    def test_design_patterns(self):
        r = self.client.get(reverse('ecosystem.design_patterns'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/design_patterns.html')

    def test_publish_review(self):
        r = self.client.get(reverse('ecosystem.publish_review'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/publish_review.html')

    def test_publish_deploy(self):
        r = self.client.get(reverse('ecosystem.publish_deploy'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/publish_deploy.html')

    def test_publish_hosted(self):
        r = self.client.get(reverse('ecosystem.publish_hosted'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/publish_hosted.html')

    def test_publish_packaged(self):
        r = self.client.get(reverse('ecosystem.publish_packaged'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/publish_packaged.html')

    def test_publish_submit(self):
        r = self.client.get(reverse('ecosystem.publish_submit'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/publish_submit.html')

    def test_build_quick(self):
        r = self.client.get(reverse('ecosystem.build_quick'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/build_quick.html')

    def test_build_intro(self):
        r = self.client.get(reverse('ecosystem.build_intro'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/build_intro.html')

    def test_build_reference(self):
        r = self.client.get(reverse('ecosystem.build_reference'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/build_reference.html')

    def test_build_ffos(self):
        r = self.client.get(reverse('ecosystem.build_ffos'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/build_ffos.html')

    def test_build_manifests(self):
        r = self.client.get(reverse('ecosystem.build_manifests'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/build_manifests.html')

    def test_build_app_generator(self):
        r = self.client.get(reverse('ecosystem.build_app_generator'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/build_app_generator.html')

    def test_build_apps_offline(self):
        r = self.client.get(reverse('ecosystem.build_apps_offline'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/build_apps_offline.html')

    def test_build_game_apps(self):
        r = self.client.get(reverse('ecosystem.build_game_apps'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/build_game_apps.html')

    def test_build_mobile_developers(self):
        r = self.client.get(reverse('ecosystem.build_mobile_developers'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/build_mobile_developers.html')

    def test_build_tools(self):
        r = self.client.get(reverse('ecosystem.build_tools'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/build_tools.html')

    def test_build_web_developers(self):
        r = self.client.get(reverse('ecosystem.build_web_developers'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/build_web_developers.html')

    def test_build_dev_tools(self):
        r = self.client.get(reverse('ecosystem.build_dev_tools'))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ecosystem/build_dev_tools.html')
