# -*- coding: utf-8 -*-
from django.conf import settings
from django.utils import translation

from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from amo.utils import urlparams
from addons.models import Category


class TestDecorators(amo.tests.TestCase):

    def test_valid_locale(self):
        url = reverse('localizers.locale_dashboard',
                      kwargs=dict(locale_code=settings.AMO_LANGUAGES[0]))
        res = self.client.head(url)
        eq_(res.status_code, 200)

    def test_hidden_locale(self):
        url = reverse('localizers.locale_dashboard',
                      kwargs=dict(locale_code=settings.HIDDEN_LANGUAGES[0]))
        res = self.client.head(url)
        eq_(res.status_code, 200)

    def test_invalid_locale(self):
        url = reverse('localizers.locale_dashboard',
                      kwargs=dict(locale_code='xx'))
        res = self.client.head(url)
        eq_(res.status_code, 404)

    def test_locale_switcher(self):
        # Test valid locale redirect.
        from_locale = settings.AMO_LANGUAGES[0]
        to_locale = settings.AMO_LANGUAGES[1]
        from_url = reverse('localizers.locale_dashboard',
                           kwargs=dict(locale_code=from_locale))
        to_url = reverse('localizers.locale_dashboard',
                         kwargs=dict(locale_code=to_locale))
        res = self.client.get(urlparams(from_url, userlang=to_locale),
                              follow=True)
        self.assertRedirects(res, to_url, status_code=302)

        # Test invalid locale, which doesn't redirect.
        to_locale = 'xx'
        to_url = reverse('localizers.locale_dashboard',
                         kwargs=dict(locale_code=to_locale))
        res = self.client.get(urlparams(from_url, userlang=to_locale),
                              follow=True)
        eq_(res.status_code, 200)


class TestCategory(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.cat1 = Category.objects.create(name='Causes',
                                            type=amo.ADDON_EXTENSION)
        self.cat1.name = {'es': u'Campañas', 'zh-CN': u'原因'}
        self.cat1.save()

        self.cat2 = Category.objects.create(name='Music',
                                            type=amo.ADDON_EXTENSION)
        self.cat2.name = {'zh-CN': u'音乐'}
        self.cat2.save()

        assert self.client.login(username='admin@mozilla.com',
                                 password='password')

    def test_permissions(self):
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        url = reverse('localizers.categories', kwargs=dict(locale_code='es'))
        res = self.client.get(url)
        eq_(res.status_code, 403)

    def test_the_basics(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        # Test page loads and names are as we expect.
        url = reverse('localizers.categories', kwargs=dict(locale_code='es'))
        res = self.client.get(url)
        eq_(res.status_code, 200)
        doc = pq(res.content.decode('utf-8'))
        eq_(doc('#id_form-0-name').val(), u'Campañas')

    def test_the_basics_other_locale(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        # Test page loads and the page UI remains in the user's locale.
        with self.activate(locale='de'):
            url = reverse('localizers.categories',
                          kwargs=dict(locale_code='es'))
            res = self.client.get(url)
            eq_(res.status_code, 200)
            doc = pq(res.content.decode('utf-8'))
            # Site UI (logout link) is in German.
            eq_(doc('.nomenu a').text(), u'Abmelden')
            # Form fields are in Spanish.
            eq_(doc('#id_form-0-name').val(), u'Campañas')
            # en-us column is in English.
            eq_(doc('td.enus').eq(0).text(), u'Causes')

    def test_other_local(self):
        # Test that somethign other than /en-US/ as the site locale doesn't
        # affect the left hand column category names.
        with self.activate(locale='es'):
            url = reverse('localizers.categories',
                          kwargs=dict(locale_code='es'))
            res = self.client.get(url)
            eq_(res.status_code, 200)
            doc = pq(res.content.decode('utf-8'))
            eq_(doc('#id_form-0-name').val(), u'Campañas')
            eq_(doc('td.enus').eq(0).text(), u'Causes')

    def test_post(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        url = reverse('localizers.categories', kwargs=dict(locale_code='es'))
        data = {
            'form-TOTAL_FORMS': 2,
            'form-INITIAL_FORMS': 2,
            'form-0-id': self.cat1.id,
            'form-0-name': u'Nada',
            'form-1-id': self.cat2.id,
            'form-1-name': u'Música',
        }
        res = self.client.post(url, data, follow=True)
        self.assertRedirects(res, url, status_code=302)
        doc = pq(res.content.decode('utf-8'))
        eq_(doc('#id_form-0-name').val(), u'Nada')
        eq_(doc('#id_form-1-name').val(), u'Música')
        translation.activate('es')
        # Test translation change.
        cat = Category.objects.get(pk=self.cat1.id)
        eq_(cat.name, u'Nada')
        # Test new translation.
        cat = Category.objects.get(pk=self.cat2.id)
        eq_(cat.name, u'Música')
        translation.deactivate()

    def test_post_with_empty_translations(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        url = reverse('localizers.categories', kwargs=dict(locale_code='es'))
        data = {
            'form-TOTAL_FORMS': 2,
            'form-INITIAL_FORMS': 2,
            'form-0-id': self.cat1.id,
            'form-0-name': u'Campañas',  # Didn't change.
            'form-1-id': self.cat2.id,
            'form-1-name': u'',  # Did not enter translation.
        }
        res = self.client.post(url, data, follow=True)
        self.assertRedirects(res, url, status_code=302)
        doc = pq(res.content.decode('utf-8'))
        eq_(doc('#id_form-0-name').val(), u'Campañas')
        eq_(doc('#id_form-1-name').val(), None)
        translation.activate('es')
        # Test translation change.
        cat = Category.objects.get(pk=self.cat1.id)
        eq_(cat.name, u'Campañas')
        # Test new translation.
        cat = Category.objects.get(pk=self.cat2.id)
        eq_(cat.name.localized_string, u'Music')  # en-US fallback.
        translation.deactivate()
