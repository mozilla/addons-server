from django.test import client

import test_utils
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
from amo.urlresolvers import reverse
from search import forms


def test_form_version_label():
    for app in amo.APP_USAGE:
        r = client.Client().get('/en-US/{0}/'.format(app.short))
        doc = pq(r.content)
        eq_(doc('#advanced-search label')[0].text,
                '%s Version' % unicode(app.pretty))


def test_korean():
    "All forms, regardless of nationality, should have an 'Any' version."
    r = client.Client().get('/ko/firefox/')
    doc = pq(r.content)
    eq_(doc('#id_lver option')[0].values()[0], 'any')


class TestSearchForm(test_utils.TestCase):
    fixtures = ('base/appversion', 'addons/persona',)

    def test_get_app_versions(self):
        actual = forms.get_app_versions(amo.FIREFOX)
        expected = [('any', 'Any'), ('3.6', '3.6'),
                    ('3.5', '3.5'), ('3.0', '3.0'), ]

        # So you added a new appversion and this broke?  Sorry about that.
        eq_(actual, expected)

    def test_personas_selected(self):
        r = self.client.get(reverse('browse.personas'), follow=True)
        doc = pq(r.content)
        eq_(doc('#cat option:selected').val(), 'personas')

        # detail page
        r = self.client.get(reverse('addons.detail', args=[15663]),
                            follow=True)
        doc = pq(r.content)
        eq_(doc('#cat option:selected').val(), 'personas')

    def test_no_personas(self):
        """Sunbird, Mobile and Seamonkey don't have personas.  So don't
        persuade people to search for them."""
        apps = ('sunbird', 'mobile', 'seamonkey',)

        for app in apps:
            r = self.client.get('/en-US/%s/' % app, follow=True)
            doc = pq(r.content)
            eq_(len(doc('.cat-all [value=personas]')), 0,
                '%s shows personas' % app)
