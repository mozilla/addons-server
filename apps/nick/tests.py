from django.core.management import call_command
from django.core.cache import cache

from nose.tools import eq_
import test_utils

from amo.urlresolvers import reverse
from applications.models import Application


class TestViews(test_utils.TestCase):
    fixtures = ('base/users', 'base/addon_3615', 'base/addon_59',
                'nick/test_views',)

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        cache.clear()

    def test_basics(self):
        """Make sure everything the template expects is available."""
        url = reverse('nick.featured')
        response = self.client.get(url, follow=True)


    def test_featured(self):
        url = reverse('nick.featured')
        response = self.client.get(url, follow=True)
        eq_(response.status_code, 200)

        eq_('featured', response.context['section'])

        addons = response.context['addons'].object_list
        eq_(len(addons), 1)

        addon = addons[0]
        eq_(addon.id, 3615)
        assert hasattr(addon, 'downloads')
        assert hasattr(addon, 'adus')
        assert hasattr(addon, 'sparks')
        eq_(addon.first_category, addon.categories.all()[0])

    def test_category_featured(self):
        url = reverse('nick.category_featured')
        response = self.client.get(url, follow=True)
        eq_(response.status_code, 200)

    def test_combo(self):
        url = reverse('nick.combo')
        response = self.client.get(url, follow=True)
        eq_(response.status_code, 200)
        addons = response.context['addons'].object_list
        eq_(len(addons), 1)

    def test_popular(self):
        url = reverse('nick.popular') + '?category=tabs'
        response = self.client.get(url, follow=True)
        eq_(response.status_code, 200)
