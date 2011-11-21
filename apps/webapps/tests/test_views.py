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
from addons.models import Addon, AddonUser, AddonPremium
from addons.tests.test_views import add_addon_author, test_hovercards
from browse.tests import test_listing_sort, test_default_sort, TestMobileHeader
from market.models import Price
from sharing import SERVICES
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


class TestPremium(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)
        self.url = reverse('apps.home')
        self.user = UserProfile.objects.get(email='regular@mozilla.com')

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

        # For measure add a free app but don't set the premium_type.
        AddonPremium.objects.create(price=price,
            addon=amo.tests.addon_factory(type=amo.ADDON_WEBAPP))

        self.free = sorted(self.free, key=lambda x: x.weekly_downloads,
                           reverse=True)
        eq_(self.free, list(Webapp.objects.top_free()))
        self.paid = sorted(self.paid, key=lambda x: x.weekly_downloads,
                           reverse=True)
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


class TestHeader(WebappTest):

    def setUp(self):
        super(TestHeader, self).setUp()
        self.home = reverse('apps.home')
        self.url = reverse('apps.list')

    def test_header(self):
        for url in (self.url, self.home):
            r = self.client.get(url)
            eq_(r.status_code, 200)
            doc = pq(r.content)
            eq_(doc('h1.site-title').text(), 'Apps')
            eq_(doc('#site-nav.app-nav').length, 1)
            eq_(doc('#search-q').attr('placeholder'), 'search for apps')

    def test_header_links(self):
        response = self.client.get(self.url)
        doc = pq(response.content)('#site-nav')
        eq_(doc('#most-popular-apps a').attr('href'),
            self.url + '?sort=downloads')
        eq_(doc('#featured-apps a').attr('href'), self.url + '?sort=featured')
        eq_(doc('#submit-app a').attr('href'), reverse('devhub.submit_apps.1'))
        eq_(doc('#my-apps a').attr('href'), reverse('users.purchases'))

    @patch.object(settings, 'READ_ONLY', False)
    def test_balloons_no_readonly(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        eq_(doc('#site-notice').length, 0)
        eq_(doc('#site-nonfx').length, 0)
        eq_(doc('#site-welcome').length, 0)
        eq_(doc('#site-noinstall-apps').length, 1)

    @patch.object(settings, 'READ_ONLY', True)
    def test_balloons_readonly(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        eq_(doc('#site-notice').length, 1)
        eq_(doc('#site-nonfx').length, 0)
        eq_(doc('#site-welcome').length, 0)
        eq_(doc('#site-noinstall-apps').length, 1)

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
        apps = test_listing_sort(self, 'free', 'weekly_downloads')
        for a in apps:
            eq_(a.is_premium(), False)

    def test_paid_sort(self):
        apps = test_listing_sort(self, 'paid', 'weekly_downloads')
        for a in apps:
            eq_(a.is_premium(), True)

    def test_price_sort(self):
        apps = test_listing_sort(self, 'price', None, reverse=False,
                                 sel_class='extra-opt')
        eq_(apps, list(Webapp.objects.filter(premium_type=amo.ADDON_PREMIUM)
                       .order_by('addonpremium__price__price')))

    def test_rating_sort(self):
        test_listing_sort(self, 'rating', 'bayesian_rating')

    def test_newest_sort(self):
        test_listing_sort(self, 'created', 'created', sel_class='extra-opt')

    def test_name_sort(self):
        test_listing_sort(self, 'name', 'name', reverse=False,
                          sel_class='extra-opt')

    def test_updated_sort(self):
        test_listing_sort(self, 'updated', 'last_updated',
                          sel_class='extra-opt')

    def test_upandcoming_sort(self):
        test_listing_sort(self, 'hotness', 'hotness', sel_class='extra-opt')


class TestDetail(WebappTest):
    fixtures = ['base/apps', 'base/addon_3615', 'base/addon_592', 'base/users']

    def get_more_pq(self):
        more_url = self.webapp.get_url_path(more=True)
        return pq(self.client.get_ajax(more_url).content.decode('utf-8'))

    def test_title(self):
        response = self.client.get(self.url)
        eq_(pq(response.content)('title').text(), 'woo :: Apps Marketplace')

    def test_downloads(self):
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#weekly-downloads').text().split()[0],
            numberfmt(self.webapp.weekly_downloads))
        self.webapp.update(weekly_downloads=0)
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#weekly-downloads').length, 0)

    def test_more_url(self):
        response = self.client.get(self.url)
        eq_(pq(response.content)('#more-webpage').attr('data-more-url'),
            self.webapp.get_url_path(more=True))

    def test_headings(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        eq_(doc('#addon h1').text(), 'woo')
        eq_(doc('section.primary.island.c h2:first').text(), 'About this App')

    def test_add_review_link_aside(self):
        r = self.client.get(self.url)
        eq_(pq(r.content)('#reviews-link').attr('href'),
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


class TestMobileAppHeader(TestMobileHeader):
    fixtures = ['base/users']

    def setUp(self):
        self.url = reverse('apps.list')


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
        url = iri_to_uri(SERVICES['delicious'].url.format(**d))
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
