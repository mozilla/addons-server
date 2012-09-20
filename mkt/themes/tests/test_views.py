import json

from addons.models import Addon, AddonCategory, AddonUser, Category, Persona
import amo
import amo.tests
from amo.tests import addon_factory
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
from reviews.models import Review
from versions.models import License

from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle


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

        Review.objects.create(addon=self.addon, user_id=999)

        (waffle.models.Switch.objects
               .create(name='personas-migration-completed', active=True))
        waffle.models.Switch.objects.create(name='mkt-themes', active=True)
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
        eq_(pq(r.content)('#more-artist').length, 1)

    def test_not_themes(self):
        other = addon_factory(type=amo.ADDON_EXTENSION)
        self.create_addon_user(other)
        r = self.client.get(self.url)
        eq_(pq(r.content)('#more-artist').length, 0)

    def test_new_more_themes(self):
        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        self.persona.persona_id = 0
        self.persona.save()
        r = self.client.get(self.url)
        eq_(pq(r.content)('#more-artist').length, 1)

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
        a = pq(r.content)('#more-artist .more a')
        eq_(a.length, 1)
        eq_(a.attr('href'), other.get_url_path())

    def test_authors(self):
        """Test whether author name works."""
        r = self.client.get(self.url)
        assert pq(r.content)('h2.authors').text().startswith('regularuser')

    def test_reviews(self):
        self.create_switch('ratings')
        r = self.client.get(self.url)
        eq_(pq(r.content)('li.review').length, 1)


class TestCategoryLandingTheme(amo.tests.TestCase):
    fixtures = ['addons/persona', 'base/users']

    def setUp(self):
        self.category = Category.objects.create(slug='nature',
                                                type=amo.ADDON_PERSONA)

        self.addons = [
            Addon.objects.get(id=15663),
            amo.tests.addon_factory(type=amo.ADDON_PERSONA, popularity=200),
            amo.tests.addon_factory(type=amo.ADDON_PERSONA, popularity=100),
            amo.tests.addon_factory(type=amo.ADDON_PERSONA, popularity=300)
        ]
        for addon in self.addons:
            AddonCategory.objects.create(addon=addon, category=self.category)

        self.url = reverse('themes.browse', args=[self.category.slug])

        waffle.models.Switch.objects.create(name='mkt-themes', active=True)

    def get_pks(self, key, url, data=None):
        r = self.client.get(url, data or {})
        eq_(r.status_code, 200)
        return sorted(x.id for x in r.context[key])

    def get_new_cat(self):
        return Category.objects.create(name='Slap Tickling', slug='booping',
                                       type=amo.ADDON_PERSONA)

    def test_good_cat(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_bad_cat(self):
        r = self.client.get(reverse('themes.browse', args=['xxx']))
        eq_(r.status_code, 404)

    def test_no_cat(self):
        r = self.client.get(reverse('themes.browse'))
        eq_(r.status_code, 200)

    def test_popular(self):
        # Popular for this category.
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        results = r.context['popular']

        # Test correct apps.
        eq_(sorted([addon.pk for addon in self.addons]),
            sorted(r.id for r in results))

        # Test sort order.
        expected = sorted(results, key=lambda x: x.persona.popularity,
                          reverse=True)
        eq_(list(results), expected)

        # Test public.
        for r in results:
            eq_(r.status, amo.STATUS_PUBLIC)

        # Check that these themes are not shown for another category.
        new_cat_url = reverse('themes.browse', args=[self.get_new_cat().slug])
        eq_(self.get_pks('popular', new_cat_url), [])


class TestSubmitTheme(amo.tests.TestCase):
    fixtures = ['base/category', 'base/licenses', 'base/users',
                'base/thunderbird.json']

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        waffle.models.Switch.objects.get_or_create(name='mkt-themes',
                                                   active=True)

        License.objects.create(id=amo.LICENSE_COPYRIGHT.id)
        header_img = get_image_path('persona-header.jpg')
        res = self.client.post(reverse('submit.theme.upload',
                                       args=['persona_header']),
                               {'upload_image': open(header_img, 'rb')})
        header_hash = json.loads(res.content)['upload_hash']
        footer_img = get_image_path('persona-footer.jpg')
        res = self.client.post(reverse('submit.theme.upload',
                                       args=['persona_footer']),
                               {'upload_image': open(footer_img, 'rb')})
        footer_hash = json.loads(res.content)['upload_hash']
        self.data = {
            'category': '1',
            'name': 'testpersona',
            'slug': 'testslug',
            'summary': 'testsummary',
            'tags': 'tag1, tag2',
            'license': amo.LICENSE_COPYRIGHT.id,
            'accentcolor': '#000000',
            'textcolor': '#ffffff',
            'header_hash': header_hash,
            'footer_hash': footer_hash,
        }

    def test_submit_theme(self):
        res = self.client.post(reverse('submit.theme'), data=self.data)

        eq_(Addon.objects.count(), 1)
        eq_(Persona.objects.count(), 1)

        addon = Addon.objects.all()[0]
        persona = Persona.objects.all()[0]

        self.assert3xx(res, reverse('submit.theme.done', args=[addon.slug]))

        eq_(addon.name, self.data['name'])
        eq_(addon.slug, self.data['slug'])
        eq_(addon.categories.all()[0].id, 1)
        eq_(addon.authors.all()[0].username, 'admin')
        eq_(addon.description, self.data['summary'])
        eq_(addon.status, amo.STATUS_PENDING)
        eq_(addon.type, amo.ADDON_PERSONA)
        eq_(persona.addon, addon)
        eq_(persona.license_id, int(self.data['license']))
        eq_(persona.display_username, 'admin')
        eq_(persona.accentcolor, self.data['accentcolor'][1:])
        eq_(persona.textcolor, self.data['textcolor'][1:])

        res = self.client.get(reverse('submit.theme.done', args=[addon.slug]))
        eq_(res.status_code, 200)

    def bad_data_gen(self, **kwargs):
        data = dict(self.data)
        data.update(kwargs)
        try:
            self.client.post(reverse('submit.theme'), data=data)
        except IOError:
            pass
        eq_(Addon.objects.count(), 0)
        eq_(Persona.objects.count(), 0)

    def test_bad_hashes(self):
        self.bad_data_gen(header_hash='ngokewashere')
        self.bad_data_gen(footer_hash='kaboodle')

    def test_blank_fields(self):
        self.bad_data_gen(name='')
        self.bad_data_gen(slug='')
        self.bad_data_gen(category='')
        self.bad_data_gen(license='')
