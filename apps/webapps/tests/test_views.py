import json

from django.conf import settings
from django.utils.encoding import iri_to_uri

from mock import patch
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

import amo
from amo.helpers import absolutify, numberfmt, page_title
import amo.tests
from amo.urlresolvers import reverse
from amo.utils import urlparams
from addons.models import Addon, AddonCategory, AddonUser, Category
from addons.tests.test_views import add_addon_author, test_hovercards
from browse.tests import test_listing_sort, test_default_sort, TestMobileHeader
from market.models import AddonPremium, Price
from sharing import get_service
from tags.models import AddonTag, Tag
from translations.helpers import truncate
from users.models import UserProfile
from versions.models import Version
from webapps.models import Webapp


class WebappTest(amo.tests.TestCase):

    def setUp(self):
        self.webapp = Webapp.objects.create(name='woo', app_slug='yeah',
            weekly_downloads=9999, status=amo.STATUS_PUBLIC)
        self.webapp._current_version = (Version.objects
                                        .create(addon=self.webapp))
        self.webapp.save()

        self.webapp_url = self.url = self.webapp.get_url_path()


class PaidAppMixin(object):

    def setup_paid(self):
        self.free = [
            Webapp.objects.get(id=337141),
            amo.tests.addon_factory(type=amo.ADDON_WEBAPP),
        ]

        self.paid = []
        for x in xrange(1, 3):
            price = Price.objects.create(price=x)
            addon = amo.tests.addon_factory(type=amo.ADDON_WEBAPP,
                                            weekly_downloads=x * 100)
            AddonPremium.objects.create(price=price, addon=addon)
            addon.update(premium_type=amo.ADDON_PREMIUM)
            self.paid.append(addon)

        # For measure add some disabled free apps ...
        amo.tests.addon_factory(type=amo.ADDON_WEBAPP, disabled_by_user=True)
        amo.tests.addon_factory(type=amo.ADDON_WEBAPP, status=amo.STATUS_NULL)

        # ... and some disabled paid apps.
        addon = amo.tests.addon_factory(type=amo.ADDON_WEBAPP,
            disabled_by_user=True, premium_type=amo.ADDON_PREMIUM)
        AddonPremium.objects.create(price=price, addon=addon)
        addon = amo.tests.addon_factory(type=amo.ADDON_WEBAPP,
            status=amo.STATUS_NULL, premium_type=amo.ADDON_PREMIUM)
        AddonPremium.objects.create(price=price, addon=addon)

        self.both = sorted(self.free + self.paid,
                           key=lambda x: x.weekly_downloads, reverse=True)
        self.free = sorted(self.free, key=lambda x: x.weekly_downloads,
                           reverse=True)
        self.paid = sorted(self.paid, key=lambda x: x.weekly_downloads,
                           reverse=True)


class TestPremium(PaidAppMixin, amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)
        self.url = reverse('apps.home')
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.setup_paid()
        eq_(self.free, list(Webapp.objects.top_free()))
        eq_(self.paid, list(Webapp.objects.top_paid()))


class TestHome(TestPremium):

    def test_free(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(list(r.context['free']), self.free)
        for idx, element in enumerate(doc('#top-free .item')):
            item = pq(element)
            webapp = self.free[idx]
            eq_(item.find('.price').text(), 'FREE')
            eq_(item.find('.downloads').split()[0],
                numberfmt(webapp.weekly_downloads))

    def test_paid(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(list(r.context['paid']), self.paid)
        for idx, element in enumerate(doc('#top-paid .item')):
            item = pq(element)
            webapp = self.paid[idx]
            eq_(item.find('.price').text(), webapp.premium.get_price_locale())
            eq_(item.find('.downloads').split()[0],
                numberfmt(webapp.weekly_downloads))


class TestLayout(WebappTest):

    def setUp(self):
        super(TestLayout, self).setUp()
        self.url = reverse('apps.home')

    def test_header(self):
        for url in (self.url, reverse('apps.list')):
            r = self.client.get(url)
            eq_(r.status_code, 200)
            doc = pq(r.content)
            eq_(doc('h1.site-title').text(), 'Apps')
            eq_(doc('#site-nav.app-nav').length, 1)
            eq_(doc('#search-q').attr('placeholder'), 'search for apps')

    def test_header_links(self):
        browse = reverse('apps.list')
        cat = Category.objects.create(name='Games', slug='games',
                                      type=amo.ADDON_WEBAPP)
        expected = [
            ('Most Popular', urlparams(browse, sort='downloads')),
            ('Top Free', urlparams(browse, sort='free')),
            ('Top Paid', urlparams(browse, sort='paid')),
            ('Highest Rated', urlparams(browse, sort='rating')),
            ('Games', cat.get_url_path()),
        ]

        r = self.client.get(self.url)
        doc = pq(r.content)('#site-nav')

        amo.tests.check_links(expected, doc('#explore-cats li a'))
        eq_(doc('#my-apps a').attr('href'), reverse('users.purchases'))
        eq_(doc('#submit-app a').attr('href'), reverse('devhub.submit_apps.1'))

    @patch.object(settings, 'READ_ONLY', False)
    def test_balloons_no_readonly(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        eq_(doc('#site-notice').length, 0)
        eq_(doc('#site-nonfx').length, 0)
        eq_(doc('#site-welcome').length, 0)
        eq_(doc('#site-nojs-apps').length, 1)
        eq_(doc('#appruntime-pitch').length, 1)

    @patch.object(settings, 'READ_ONLY', True)
    def test_balloons_readonly(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        eq_(doc('#site-notice').length, 1)
        eq_(doc('#site-nonfx').length, 0)
        eq_(doc('#site-welcome').length, 0)
        eq_(doc('#site-nojs-apps').length, 1)
        eq_(doc('#appruntime-pitch').length, 1)

    def test_footer(self):
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#social-footer').length, 0)
        eq_(doc('#copyright').length, 1)
        eq_(doc('#footer-links .mobile-link').length, 1)

    def test_search_url(self):
        for url in (self.url, self.webapp_url):
            response = self.client.get(url)
            doc = pq(response.content)
            eq_(doc('#search').attr('action'), '/en-US/apps/search/')


class TestListing(TestPremium):

    def setUp(self):
        super(TestListing, self).setUp()
        self.url = reverse('apps.list')

    def test_default_sort(self):
        test_default_sort(self, 'downloads', 'weekly_downloads')

    def test_free_sort(self):
        for app in test_listing_sort(self, 'free', 'weekly_downloads'):
            eq_(app.is_premium(), False)

    def test_paid_sort(self):
        for app in test_listing_sort(self, 'paid', 'weekly_downloads'):
            eq_(app.is_premium(), True)

    def test_price_sort(self):
        apps = test_listing_sort(self, 'price', None, reverse=False,
                                 sel_class='extra-opt')
        eq_(apps, list(Webapp.objects.listed()
                       .order_by('addonpremium__price__price', 'id')))

    def test_rating_sort(self):
        test_listing_sort(self, 'rating', 'bayesian_rating')

    def test_newest_sort(self):
        test_listing_sort(self, 'created', 'created', sel_class='extra-opt')

    def test_name_sort(self):
        test_listing_sort(self, 'name', 'name', reverse=False,
                          sel_class='extra-opt')


class TestDetail(WebappTest):
    fixtures = ['base/apps', 'base/addon_3615', 'base/addon_592', 'base/users']

    def get_pq(self):
        return pq(self.client.get(self.url).content.decode('utf-8'))

    def get_more_pq(self):
        more_url = self.webapp.get_url_path(more=True)
        return pq(self.client.get_ajax(more_url).content.decode('utf-8'))

    def test_title(self):
        eq_(self.get_pq()('title').text(), 'woo :: Apps Marketplace')

    def test_downloads(self):
        dls = self.get_pq()('#weekly-downloads')
        eq_(dls.find('a').length, 0)
        eq_(dls.text().split()[0], numberfmt(self.webapp.weekly_downloads))
        self.webapp.update(weekly_downloads=0)
        eq_(self.get_pq()('#weekly-downloads').length, 0)

    def test_more_url(self):
        eq_(self.get_pq()('#more-webpage').attr('data-more-url'),
            self.webapp.get_url_path(more=True))

    def test_headings(self):
        doc = self.get_pq()
        eq_(doc('#addon h1').text(), 'woo')
        eq_(doc('section.primary.island.c h2:first').text(), 'About this App')

    def test_add_review_link_aside(self):
        eq_(self.get_pq()('#reviews-link').attr('href'),
            reverse('apps.reviews.list', args=[self.webapp.app_slug]))

    def test_add_review_link_more(self):
        doc = self.get_more_pq()
        add_url = reverse('apps.reviews.add', args=[self.webapp.app_slug])
        eq_(doc.find('#reviews #add-first-review').attr('href'), add_url)
        eq_(doc.find('#reviews h3').remove('a').text(),
            'This app has not yet been reviewed.')
        eq_(doc.find('#add-review').attr('href'), add_url)

    def test_other_apps(self):
        """Ensure listed apps by the same author show up."""
        # Create a new webapp.
        Addon.objects.get(id=592).update(type=amo.ADDON_WEBAPP)
        other = Webapp.objects.get(id=592)
        eq_(list(Webapp.objects.listed().exclude(id=self.webapp.id)), [other])

        author = add_addon_author(other, self.webapp)
        doc = self.get_more_pq()('#author-addons')
        eq_(doc.length, 1)

        by = doc.find('h2 a')
        eq_(by.attr('href'), author.get_url_path())
        eq_(by.text(), author.name)

        test_hovercards(self, doc, [other], src='dp-dl-othersby')

    def test_other_apps_no_addons(self):
        """An add-on by the same author should not show up."""
        other = Addon.objects.get(id=592)
        assert other.type != amo.ADDON_WEBAPP, 'Should not be an app.'

        add_addon_author(other, self.webapp)
        eq_(self.get_more_pq()('#author-addons').length, 0)

    def test_other_apps_no_unlisted(self):
        """An unlisted app by the same author should not show up."""
        Addon.objects.get(id=592).update(type=amo.ADDON_WEBAPP,
                                         disabled_by_user=True)
        other = Webapp.objects.get(id=592)

        add_addon_author(other, self.webapp)
        eq_(self.get_more_pq()('#author-addons').length, 0)

    def test_other_apps_by_others(self):
        """Apps by different/no authors should not show up."""
        author = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=self.webapp, user=author, listed=True)
        eq_(self.get_more_pq()('#author-addons').length, 0)

    def test_other_apps_none(self):
        eq_(self.get_more_pq()('#author-addons').length, 0)

    def test_deleted(self):
        self.webapp.update(status=amo.STATUS_DELETED)
        r = self.client.get(self.url)
        eq_(r.status_code, 404)

    def test_disabled_user_message(self):
        self.webapp.update(disabled_by_user=True)
        r = self.client.get(self.url)
        eq_(r.status_code, 404)
        doc = pq(r.content)
        h1 = doc('h1.addon')
        eq_(h1.length, 1)
        eq_(h1.find('a').length, 0)
        assert pq(r.content)('.removed'), (
          'Expected message indicating that app was removed by its author')

    def test_disabled_status_message(self):
        self.webapp.update(status=amo.STATUS_DISABLED)
        r = self.client.get(self.url)
        eq_(r.status_code, 404)
        doc = pq(r.content)
        h1 = doc('h1.addon')
        eq_(h1.length, 1)
        eq_(h1.find('a').length, 0)
        assert pq(r.content)('.disabled'), (
          'Expected message indicating that app was disabled by administrator')

    def test_categories(self):
        c = Category.objects.all()[0]
        c.application = None
        c.type = amo.ADDON_WEBAPP
        c.save()
        AddonCategory.objects.create(addon=self.webapp, category=c)
        links = self.get_more_pq()('#related ul:first').find('a')
        amo.tests.check_links([(unicode(c.name), c.get_url_path())], links)

    def test_tags(self):
        t = Tag.objects.create(tag_text='ballin')
        AddonTag.objects.create(tag=t, addon=self.webapp)
        links = self.get_more_pq()('#related #tagbox ul a')
        amo.tests.check_links([(t.tag_text, t.get_url_path())], links,
                              verify=False)


class TestMobileListing(amo.tests.MobileTest, WebappTest):

    def get_res(self):
        r = self.client.get(reverse('apps.list'))
        eq_(r.status_code, 200)
        return r, pq(r.content)

    def test_listing(self):
        r, doc = self.get_res()
        self.assertTemplateUsed(r, 'browse/mobile/extensions.html')
        item = doc('.item')
        eq_(item.length, 1)
        eq_(item.find('h3').text(), 'woo')

    def test_listing_downloads(self):
        r, doc = self.get_res()
        dls = doc('.item').find('details .vital.downloads')
        eq_(dls.text().split()[0], numberfmt(self.webapp.weekly_downloads))


class TestMobileLayout(TestMobileHeader):
    fixtures = ['base/users']

    def setUp(self):
        self.url = reverse('apps.list')

    @patch.object(settings, 'APP_PREVIEW', True)
    def test_no_language_selector(self):
        # When Marketplace is localized, remove this test.
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#lang_form').length, 0)

    def test_language_selector(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#lang_form').length, 1)


class TestMobileDetail(amo.tests.MobileTest, WebappTest):

    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'addons/mobile/details.html')
        doc = pq(r.content)
        eq_(doc('title').text(), '%s :: Apps Marketplace' % self.webapp.name)
        eq_(doc('h3').text(), unicode(self.webapp.name))

    def test_downloads(self):
        doc = pq(self.client.get(self.url).content)('table')
        eq_(doc('.adu').length, 0)
        eq_(doc('.downloads td').text(),
            numberfmt(self.webapp.weekly_downloads))
        self.webapp.update(weekly_downloads=0)
        doc = pq(self.client.get(self.url).content)('table')
        eq_(doc('.downloads').length, 0)

    def test_no_release_notes(self):
        r = self.client.get(self.url)
        eq_(pq(r.content)('.versions').length, 0)


class TestSharing(WebappTest):

    def test_redirect_sharing(self):
        r = self.client.get(reverse('apps.share', args=['yeah']),
                            {'service': 'delicious'})
        d = {
            'title': page_title({'request': r}, self.webapp.name,
                                force_webapps=True),
            'description': truncate(self.webapp.summary, length=250),
            'url': absolutify(self.webapp.get_url_path()),
        }
        url = iri_to_uri(get_service('delicious').url.format(**d))
        self.assertRedirects(r, url, status_code=302, target_status_code=301)


class TestReportAbuse(WebappTest):

    def setUp(self):
        super(TestReportAbuse, self).setUp()
        self.abuse_url = reverse('apps.abuse', args=[self.webapp.app_slug])

    def test_page(self):
        r = self.client.get(self.abuse_url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('title').text(), 'Report abuse for woo :: Apps Marketplace')
        expected = [
            ('Apps Marketplace', reverse('apps.home')),
            ('Apps', reverse('apps.list')),
            (unicode(self.webapp.name), self.url),
        ]
        amo.tests.check_links(expected, doc('#breadcrumbs a'))


@patch.object(settings, 'WEBAPPS_RECEIPT_KEY', amo.tests.AMOPaths.sample_key())
class TestInstall(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.addon = Addon.objects.create(type=amo.ADDON_WEBAPP)
        self.addon.update(app_slug=self.addon.pk,
                          manifest_url='http://cbc.ca/manifest')
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.url = reverse('apps.record', args=[self.addon.app_slug])
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

    def test_not_record_addon(self):
        self.addon.update(type=amo.ADDON_EXTENSION)
        self.client.post(self.url)
        eq_(self.user.installed_set.count(), 0)

    def test_record_logged_out(self):
        self.client.logout()
        res = self.client.post(self.url)
        eq_(res.status_code, 302)

    def test_record_install(self):
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.user.installed_set.count(), 1)

    def test_record_multiple_installs(self):
        self.client.post(self.url)
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.user.installed_set.count(), 1)

    @patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                  amo.tests.AMOPaths.sample_key())
    def test_record_receipt(self):
        res = self.client.post(self.url)
        content = json.loads(res.content)
        assert content.get('receipt'), content
