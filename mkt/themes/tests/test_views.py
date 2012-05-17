import amo.tests
from amo.tests import addon_factory
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

from addons.models import Addon, AddonUser

class TestPersonas(object):
    fixtures = ['addons/persona', 'base/users']

    def create_addon_user(self, addon):
        if waffle.switch_is_active('personas-migration-completed'):
            return AddonUser.objects.create(addon=addon, user_id=999)

        if addon.type == amo.ADDON_PERSONA:
            addon.persona.author = self.persona.author
            addon.persona.save()


class TestPersonaDetailPage(TestPersonas, amo.tests.TestCase):

    def setUp(self):
        self.addon = Addon.objects.get(id=15663)
        self.persona = self.addon.persona
        self.url = self.addon.get_url_path()

        # Is this still needed?
        (waffle.models.Switch.objects
               .create(name='personas-migration-completed', active=True))
        self.create_addon_user(self.addon)

    def test_theme_images(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        style = doc('.theme-large div[data-browsertheme]').attr('style')
        assert self.persona.preview_url in style, (
            'style attribute %s does not link to %s' % (
            style, self.persona.preview_url))

    def test_more_themes(self):
        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        r = self.client.get(self.url)
        eq_(pq(r.content)('#more-artist .more-link').length, 1)

    def test_not_themes(self):
        other = addon_factory(type=amo.ADDON_EXTENSION)
        self.create_addon_user(other)
        r = self.client.get(self.url)
        eq_(pq(r.content)('#more-artist .more-link').length, 0)

    def test_new_more_themes(self):
        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        self.persona.persona_id = 0
        self.persona.save()
        r = self.client.get(self.url)
        eq_(pq(r.content)('#more-artist .more-link').length, 0)

    def test_other_themes(self):
        """Ensure listed themes by the same author show up."""
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_NULL)
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_LITE)
        addon_factory(type=amo.ADDON_PERSONA, disabled_by_user=True)

        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        eq_(other.status, amo.STATUS_PUBLIC)
        eq_(other.disabled_by_user, False)

        r = self.client.get(self.url)
        eq_(list(r.context['author_themes']), [other])
        a = pq(r.content)('#more-artist a[data-browsertheme]')
        eq_(a.length, 1)
        eq_(a.attr('href'), other.get_url_path())

    def test_authors(self):
        """Test whether author name works."""
        r = self.client.get(self.url)
        assert pq(r.content)('h2.authors').text().startswith('regularuser')
