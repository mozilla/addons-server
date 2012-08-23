from urllib import urlencode

from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
from amo.urlresolvers import reverse
from devhub.models import RssKey
from devhub.tests.test_views import HubTest
from bandwagon.models import Collection
from reviews.models import Review
from tags.models import Tag
from versions.models import Version


class TestActivity(HubTest):
    """Test the activity feed."""

    def setUp(self):
        """Start with one user, two add-ons."""
        super(TestActivity, self).setUp()
        self.clone_addon(2)
        amo.set_user(self.user_profile)
        self.addon, self.addon2 = list(self.user_profile.addons.all())

    def log_creates(self, num, addon=None):
        if not addon:
            addon = self.addon
        for i in xrange(num):
            amo.log(amo.LOG.CREATE_ADDON, addon)

    def log_updates(self, num, version_string='1'):
        version = Version.objects.create(version=version_string,
                                         addon=self.addon)

        for i in xrange(num):
            amo.log(amo.LOG.ADD_VERSION, self.addon, version)

    def log_status(self, num):
        for i in xrange(num):
            amo.log(amo.LOG.USER_DISABLE, self.addon)

    def log_collection(self, num, prefix='foo'):
        for i in xrange(num):
            c = Collection.objects.create(name='%s %d' % (prefix, i))
            amo.log(amo.LOG.ADD_TO_COLLECTION, self.addon, c)

    def log_tag(self, num, prefix='foo'):
        for i in xrange(num):
            t = Tag.objects.create(tag_text='%s %d' % (prefix, i))
            amo.log(amo.LOG.ADD_TAG, self.addon, t)

    def log_review(self, num):
        r = Review(addon=self.addon)
        for i in xrange(num):
            amo.log(amo.LOG.ADD_REVIEW, self.addon, r)

    def get_response(self, **kwargs):
        url = reverse('devhub.feed_all')
        if 'addon' in kwargs:
            url = reverse('devhub.feed', args=(kwargs['addon'],))

        if kwargs:
            url += '?' + urlencode(kwargs)

        return self.client.get(url, follow=True)

    def get_pq(self, **kwargs):
        return pq(self.get_response(**kwargs).content)

    def test_dashboard(self):
        """Make sure the dashboard is getting data."""
        self.log_creates(10)
        r = self.client.get(reverse('devhub.addons'))
        doc = pq(r.content)
        eq_(len(doc('li.item')), 4)
        eq_(doc('.subscribe-feed').attr('href')[:-32],
            reverse('devhub.feed_all') + '?privaterss=')

    def test_ignore_apps_on_dashboard(self):
        self.addon.update(type=amo.ADDON_WEBAPP)
        self.log_creates(1)
        rp = self.client.get(reverse('devhub.addons'))
        doc = pq(rp.content)
        eq_(doc('li.item').text(), None)

    def test_ignore_apps_in_feed(self):
        self.addon.update(type=amo.ADDON_WEBAPP)
        self.log_creates(1)
        rp = self.get_response()
        doc = pq(rp.content)
        eq_(doc('.item').text(), None)

    def test_items(self):
        self.log_creates(10)
        doc = self.get_pq()
        eq_(len(doc('.item')), 10)

    def test_filter_persistence(self):
        doc = self.get_pq(action='status')
        assert '?action=status' in (doc('ul.refinements').eq(0)('a').eq(1)
                                    .attr('href'))

    def test_filter_updates(self):
        self.log_creates(10)
        self.log_updates(10)
        doc = self.get_pq()
        eq_(len(doc('.item')), 20)
        doc = self.get_pq(action='updates')
        eq_(len(doc('.item')), 10)

    def test_filter_status(self):
        self.log_creates(10)
        self.log_status(5)
        doc = self.get_pq()
        eq_(len(doc('.item')), 15)
        doc = self.get_pq(action='status')
        eq_(len(doc('.item')), 5)

    def test_filter_collections(self):
        self.log_creates(10)
        self.log_collection(3)
        doc = self.get_pq()
        eq_(len(doc('.item')), 13)
        doc = self.get_pq(action='collections')
        eq_(len(doc('.item')), 3)

    def test_filter_reviews(self):
        self.log_creates(10)
        self.log_review(10)
        doc = self.get_pq()
        eq_(len(doc('.item')), 20)
        doc = self.get_pq(action='reviews')
        eq_(len(doc('.item')), 10)

    def test_pagination(self):
        self.log_review(21)
        doc = self.get_pq()

        # 20 items on page 1.
        eq_(len(doc('.item')), 20)

        # 1 item on page 2
        doc = self.get_pq(page=2)
        eq_(len(doc('.item')), 1)

        # we have a pagination thingy
        eq_(len(doc('.pagination')), 1)
        assert doc('.listing-footer')

    def test_no_pagination(self):
        doc = self.get_pq()
        assert not doc('.listing-footer')

    def test_filter_addon(self):
        self.log_creates(10)
        self.log_creates(13, self.addon2)

        # We show everything without filters
        doc = self.get_pq()
        eq_(len(doc('.item')), 20)

        # We just show addon1
        doc = self.get_pq(addon=self.addon.id)
        eq_(len(doc('.item')), 10)

        # we just show addon2
        doc = self.get_pq(addon=self.addon2.id)
        eq_(len(doc('.item')), 13)

    def test_filter_addon_admin(self):
        """Admins should be able to see specific pages."""
        self.log_creates(10)
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        r = self.get_response(addon=self.addon.id)
        eq_(r.status_code, 200)

    def test_filter_addon_otherguy(self):
        """Make sure nobody else can see my precious add-on feed."""
        self.log_creates(10)
        assert self.client.login(username='clouserw@gmail.com',
                                 password='password')
        r = self.get_response(addon=self.addon.id)
        eq_(r.status_code, 403)

    def test_rss(self):
        self.log_creates(5)
        # This will give us a new RssKey
        r = self.get_response()
        key = RssKey.objects.get()
        r = self.get_response(privaterss=key.key)
        eq_(r['content-type'], 'application/rss+xml; charset=utf-8')

    def test_rss_single(self):
        self.log_creates(5)
        self.log_creates(13, self.addon2)

        # This will give us a new RssKey
        r = self.get_response(addon=self.addon.id)
        key = RssKey.objects.get()
        r = self.get_response(privaterss=key.key)
        eq_(r['content-type'], 'application/rss+xml; charset=utf-8')
        eq_(len(pq(r.content)('item')), 5)

    def test_rss_ignores_apps(self):
        self.addon.update(type=amo.ADDON_WEBAPP)
        self.log_creates(1)
        # This will give us a new RssKey
        self.get_response()
        key = RssKey.objects.get()
        rp = self.get_response(privaterss=key.key)
        eq_(pq(rp.content)('item').text(), None)

    def test_logged_out(self):
        self.client.logout()
        r = self.get_response()
        eq_(r.redirect_chain[0][1], 302)

    def test_xss_addon(self):
        self.addon.name = ("<script>alert('Buy more Diet Mountain Dew.')"
                           '</script>')
        self.addon.save()
        self.log_creates(1)
        doc = self.get_pq()
        eq_(len(doc('.item')), 1)
        assert '<script>' not in unicode(doc), 'XSS FTL'
        assert '&lt;script&gt;' in unicode(doc), 'XSS FTL'

    def test_xss_collections(self):
        self.log_collection(1, "<script>alert('v1@gra for u')</script>")
        doc = self.get_pq()
        eq_(len(doc('.item')), 1)
        assert '<script>' not in unicode(doc), 'XSS FTL'
        assert '&lt;script&gt;' in unicode(doc), 'XSS FTL'

    def test_xss_tags(self):
        self.log_tag(1, "<script src='x.js'>")
        doc = self.get_pq()
        eq_(len(doc('.item')), 1)
        assert '<script' not in unicode(doc('.item')), 'XSS FTL'
        assert '&lt;script' in unicode(doc('.item')), 'XSS FTL'

    def test_xss_versions(self):
        self.log_updates(1, "<script src='x.js'>")
        doc = self.get_pq()
        eq_(len(doc('.item')), 2)
        assert '<script' not in unicode(doc('.item')), 'XSS FTL'
        assert '&lt;script' in unicode(doc('.item')), 'XSS FTL'

    def test_hidden(self):
        version = Version.objects.create(addon=self.addon)
        amo.log(amo.LOG.COMMENT_VERSION, self.addon, version)
        res = self.get_response(addon=self.addon.id)
        key = RssKey.objects.get()
        res = self.get_response(privaterss=key.key)
        assert "<title>Comment on" not in res.content

    def test_no_guid(self):
        self.log_creates(1)
        self.get_response(addon=self.addon.id)
        key = RssKey.objects.get()
        res = self.get_response(privaterss=key.key)
        assert "<guid>" not in res.content
