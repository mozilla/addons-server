from datetime import datetime

from django import test
from django.conf import settings
from django.core.cache import cache

from mock import Mock
from nose.tools import eq_
import test_utils
from pyquery import PyQuery as pq

import amo
from amo.helpers import urlparams
from amo.urlresolvers import reverse
from addons.models import Addon, AddonUser
from addons.views import _details_collections_dropdown
from users.models import UserProfile


class TestHomepage(test_utils.TestCase):
    fixtures = ['base/fixtures', 'base/global-stats', 'base/featured']

    def setUp(self):
        super(TestHomepage, self).setUp()
        self.base_url = reverse('home')

    def test_promo_box_public_addons(self):
        """Only public add-ons in the promobox."""
        r = self.client.get(self.base_url, follow=True)
        doc = pq(r.content)
        assert doc('.addon-view .item').length > 0

        Addon.objects.update(status=amo.STATUS_UNREVIEWED)
        cache.clear()
        r = self.client.get(self.base_url, follow=True)
        doc = pq(r.content)
        eq_(doc('.addon-view .item').length, 0)

    def test_promo_box(self):
        """Test that promobox features have proper translations."""
        r = self.client.get(self.base_url, follow=True)
        doc = pq(r.content)
        eq_(doc('.lead a')[0].text, 'WebDev')

    def test_thunderbird(self):
        """Thunderbird homepage should have the Thunderbird title."""
        r = self.client.get('/en-US/thunderbird/')
        doc = pq(r.content)
        eq_('Add-ons for Thunderbird', doc('title').text())

    def test_default_feature(self):
        response = self.client.get(self.base_url, follow=True)
        eq_(response.status_code, 200)
        eq_(response.context['filter'].field, 'featured')

    def test_featured(self):
        response = self.client.get(self.base_url + '?browse=featured',
                                   follow=True)
        eq_(response.status_code, 200)
        eq_(response.context['filter'].field, 'featured')
        featured = response.context['addon_sets']['featured']
        ids = [a.id for a in featured]
        eq_(set(ids), set([2464, 7661]))
        for addon in featured:
            assert addon.is_featured(amo.FIREFOX, settings.LANGUAGE_CODE)

    def _test_invalid_feature(self):
        response = self.client.get(self.base_url + '?browse=xxx')
        self.assertRedirects(response, '/en-US/firefox/', status_code=301)

    def test_no_unreviewed(self):
        response = self.client.get(self.base_url)
        for addons in response.context['addon_sets'].values():
            for addon in addons:
                assert addon.status != amo.STATUS_UNREVIEWED

    def test_filter_opts(self):
        response = self.client.get(self.base_url)
        opts = [k[0] for k in response.context['filter'].opts]
        eq_(opts, 'featured popular new updated'.split())

    def test_added_date(self):
        doc = pq(self.client.get(self.base_url).content)
        s = doc('#list-new .item .updated').text()
        assert s.strip().startswith('Added'), s


class TestPromobox(test_utils.TestCase):
    fixtures = ['addons/ptbr-promobox']

    def test_promo_box_ptbr(self):
        # bug 564355, we were trying to match pt-BR and pt-br
        response = self.client.get('/pt-BR/firefox/', follow=True)
        eq_(response.status_code, 200)


class TestDetailPage(test_utils.TestCase):
    fixtures = ['base/fixtures', 'base/addon_59.json', 'addons/listed',
                'addons/persona']

    def test_anonymous_user(self):
        """Does the page work for an anonymous user?"""
        # extensions
        response = self.client.get(reverse('addons.detail', args=[3615]),
                                   follow=True)
        eq_(response.status_code, 200)
        eq_(response.context['addon'].id, 3615)

        # personas
        response = self.client.get(reverse('addons.detail', args=[15663]),
                                   follow=True)
        eq_(response.status_code, 200)
        eq_(response.context['addon'].id, 15663)

    def test_inactive_addon(self):
        """Do not display disabled add-ons."""
        myaddon = Addon.objects.get(id=3615)
        myaddon.inactive = True
        myaddon.save()
        response = self.client.get(reverse('addons.detail', args=[myaddon.id]),
                                   follow=True)
        eq_(response.status_code, 404)

    def test_listed(self):
        """Show certain things for hosted but not listed add-ons."""
        hosted_resp = self.client.get(reverse('addons.detail', args=[3615]),
                                      follow=True)
        hosted = pq(hosted_resp.content)

        listed_resp = self.client.get(reverse('addons.detail', args=[3723]),
                                      follow=True)
        listed = pq(listed_resp.content)

        eq_(hosted('#releasenotes').length, 1)
        eq_(listed('#releasenotes').length, 0)

    def test_beta(self):
        """Test add-on with a beta channel."""
        my_addonid = 3615
        get_pq_content = lambda: pq(self.client.get(reverse(
            'addons.detail', args=[my_addonid]), follow=True).content)

        myaddon = Addon.objects.get(id=my_addonid)

        # Add a beta version and show it.
        mybetafile = myaddon.versions.all()[0].files.all()[0]
        mybetafile.status = amo.STATUS_BETA
        mybetafile.save()
        beta = get_pq_content()
        eq_(beta('#beta-channel').length, 1)

        # Now hide it.
        myaddon.show_beta = False
        myaddon.save()
        beta = get_pq_content()
        eq_(beta('#beta-channel').length, 0)

    def test_other_addons(self):
        """Test "other add-ons by author" list."""

        # Grab a user and give them some add-ons.
        u = UserProfile.objects.get(pk=2519)
        thisaddon = u.addons.all()[0]
        other_addons = Addon.objects.exclude(pk=thisaddon.pk)[:3]
        for addon in other_addons:
            AddonUser.objects.create(user=u, addon=addon)

        page = self.client.get(reverse('addons.detail', args=[thisaddon.id]),
                               follow=True)
        doc = pq(page.content)
        eq_(doc('.other-author-addons li').length, other_addons.count())
        for i in range(other_addons.count()):
            link = doc('.other-author-addons li a').eq(i)
            eq_(link.attr('href'), other_addons[i].get_url_path())

    def test_type_redirect(self):
        """
        If current add-on's type is unsupported by app, redirect to an
        app that supports it.
        """
        # Sunbird can't do Personas => redirect
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = amo.SUNBIRD.short
        response = self.client.get(reverse('addons.detail', args=[15663]),
                                   follow=False)
        eq_(response.status_code, 301)
        eq_(response['Location'].find(amo.SUNBIRD.short), -1)
        assert (response['Location'].find(amo.FIREFOX.short) >= 0)

    def test_compatible_app_redirect(self):
        """
        For add-ons incompatible with the current app, redirect to one
        that's supported.
        """
        addon = Addon.objects.get(id=3615)
        comp_app = addon.compatible_apps.keys()[0]
        not_comp_app = [a for a in amo.APP_USAGE
                        if a not in addon.compatible_apps.keys()][0]

        # no SeaMonkey version => redirect
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = not_comp_app.short
        response = self.client.get(reverse('addons.detail', args=[addon.id]),
                                   follow=False)
        eq_(response.status_code, 301)
        eq_(response['Location'].find(not_comp_app.short), -1)
        assert (response['Location'].find(comp_app.short) >= 0)

        # compatible app => 200
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = comp_app.short
        response = self.client.get(reverse('addons.detail', args=[addon.id]),
                                   follow=False)
        eq_(response.status_code, 200)

    def test_external_urls(self):
        """Check that external URLs are properly escaped."""
        addon = Addon.objects.get(id=1843)
        response = self.client.get(reverse('addons.detail', args=[addon.id]),
                                   follow=True)
        doc = pq(response.content)
        eq_(doc('#addon-summary a[href^="%s"]' %
                settings.REDIRECT_URL).length, 1)

    def test_other_collection_count(self):
        """Other collection count must not get negative."""
        addon = Addon.objects.get(id=1843)
        response = self.client.get(reverse('addons.detail', args=[addon.id]),
                                   follow=True)
        assert response.context['other_collection_count'] >= 0

    def test_privacy_policy(self):
        """Make sure privacy policy is shown when present."""
        addon = Addon.objects.get(id=1843)
        addon.privacy_policy = None
        addon.save()
        response = self.client.get(reverse('addons.detail', args=[addon.id]),
                                   follow=True)
        doc = pq(response.content)
        eq_(doc('.privacy-policy').length, 0)

        addon.privacy_policy = 'foo bar'
        addon.save()
        response = self.client.get(reverse('addons.detail', args=[addon.id]),
                                   follow=True)
        doc = pq(response.content)
        eq_(doc('.privacy-policy').length, 1)
        assert doc('.privacy-policy').attr('href').endswith(
            '/addons/policy/0/1843')

    def test_button_size(self):
        """Make sure install buttons on the detail page are prominent."""
        response = self.client.get(reverse('addons.detail', args=[3615]),
                                   follow=True)
        assert pq(response.content)('.button').hasClass('prominent')

    def test_invalid_version(self):
        """Only render details pages for add-ons that have a version."""
        myaddon = Addon.objects.get(id=3615)
        # wipe all versions
        myaddon.versions.all().delete()
        # try accessing the details page
        response = self.client.get(reverse('addons.detail', args=[myaddon.id]),
                                   follow=True)
        eq_(response.status_code, 404)

    def test_login_links(self):
        """Make sure the login links on this page, redirect back to itself."""
        url = reverse('addons.detail', args=[3615])
        resp = self.client.get(url, follow=True)
        if not url.startswith('/en-US/firefox'):
            url = '/en-US/firefox' + url

        sel = 'a[href$="%s"]' % urlparams(reverse('users.login'), to=url)
        doc = pq(resp.content)
        eq_(len(doc(sel)), 3)  # 3 login links

    def test_other_author_addons(self):
        """
        Make sure the list of other author addons doesn't include this one.
        """
        r = self.client.get(reverse('addons.detail', args=[8680]))
        doc = pq(r.content)
        eq_(len([a.attrib['value'] for a
                 in doc('#addons-author-addons-select option')
                 if a.attrib['value'] == '8680']), 0)

    def test_details_collections_dropdown(self):

        request = Mock()
        request.APP.id = 1
        request.user.is_authenticated = lambda: True

        request.amo_user.id = 10482

        addon = Mock()
        addon.id = 4048

        ret = _details_collections_dropdown(request, addon)
        eq_(len(ret), 2)

        # Add-on exists in one of the collections
        addon.id = 433
        ret = _details_collections_dropdown(request, addon)
        eq_(len(ret), 1)

        request.user.is_authenticated = lambda: False
        request.amo_user.id = None

        ret = _details_collections_dropdown(request, addon)
        eq_(len(ret), 0)

    def test_remove_tag_button(self):
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(reverse('addons.detail', args=[3615]))
        doc = pq(r.content)
        assert len(doc('#tags li input.removetag'))

    def test_detailed_review_link(self):
        # TODO(jbalogh): use reverse when we drop remora.
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(reverse('addons.detail', args=[3615]))
        doc = pq(r.content)
        href = doc('#review-box a[href*="reviews/add"]').attr('href')
        assert href.endswith('/reviews/add/3615'), href

    def test_no_listed_authors(self):
        r = self.client.get(reverse('addons.detail', args=[59]))
        # We shouldn't show an avatar since this has no listed_authors.
        doc = pq(r.content)
        eq_(0, len(doc('.avatar')))


class TestTagsBox(test_utils.TestCase):
    fixtures = ['base/addontag']

    def test_tag_box(self):
        """Verify that we don't show duplicate tags."""
        r = self.client.get(reverse('addons.detail', args=[8680]), follow=True)
        doc = pq(r.content)
        eq_('SEO', doc('#tags ul').children().text())


def test_button_caching():
    """The button popups should be cached for a long time."""
    # Get the url from a real page so it includes the build id.
    client = test.Client()
    doc = pq(client.get('/', follow=True).content)
    js_url = reverse('addons.buttons.js')
    url_with_build = doc('script[src^="%s"]' % js_url).attr('src')

    response = client.get(url_with_build, follow=True)
    fmt = '%a, %d %b %Y %H:%M:%S GMT'
    expires = datetime.strptime(response['Expires'], fmt)
    assert (expires - datetime.now()).days >= 365
