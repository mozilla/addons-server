import uuid

from urllib import urlencode

from pyquery import PyQuery as pq

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.amo.urlresolvers import reverse
from olympia.bandwagon.models import Collection
from olympia.devhub.models import RssKey
from olympia.devhub.tests.test_views import HubTest
from olympia.ratings.models import Rating
from olympia.tags.models import Tag
from olympia.versions.models import Version


class TestActivity(HubTest):
    """Test the activity feed."""

    def setUp(self):
        """Start with one user, two add-ons."""
        super(TestActivity, self).setUp()
        self.clone_addon(2)
        core.set_user(self.user_profile)
        self.addon, self.addon2 = list(self.user_profile.addons.all())

    def log_creates(self, num, addon=None):
        if not addon:
            addon = self.addon
        for i in xrange(num):
            ActivityLog.create(amo.LOG.CREATE_ADDON, addon)

    def log_updates(self, num, version_string='1'):
        version = Version.objects.create(
            version=version_string, addon=self.addon
        )

        for i in xrange(num):
            ActivityLog.create(amo.LOG.ADD_VERSION, self.addon, version)

    def log_status(self, num):
        for i in xrange(num):
            ActivityLog.create(amo.LOG.USER_DISABLE, self.addon)

    def log_collection(self, num, prefix='foo'):
        for i in xrange(num):
            collection = Collection.objects.create(name='%s %d' % (prefix, i))
            ActivityLog.create(
                amo.LOG.ADD_TO_COLLECTION, self.addon, collection
            )

    def log_tag(self, num, prefix='foo'):
        for i in xrange(num):
            tag = Tag.objects.create(tag_text='%s %d' % (prefix, i))
            ActivityLog.create(amo.LOG.ADD_TAG, self.addon, tag)

    def log_rating(self, num):
        rating = Rating(addon=self.addon)
        for i in xrange(num):
            ActivityLog.create(amo.LOG.ADD_RATING, self.addon, rating)

    def get_response(self, **kwargs):
        follow = kwargs.pop('follow', True)
        url = reverse('devhub.feed_all')
        if 'addon' in kwargs:
            url = reverse('devhub.feed', args=(kwargs['addon'],))

        if kwargs:
            url += '?' + urlencode(kwargs)

        return self.client.get(url, follow=follow)

    def get_pq(self, **kwargs):
        return pq(self.get_response(**kwargs).content)

    def test_dashboard(self):
        """Make sure the dashboard is getting data."""
        self.log_creates(10)
        response = self.client.get(reverse('devhub.addons'))
        doc = pq(response.content)
        assert len(doc('li.item')) == 4
        assert doc('.subscribe-feed').attr('href')[:-32] == (
            reverse('devhub.feed_all') + '?privaterss='
        )

    def test_items(self):
        self.log_creates(10)
        doc = self.get_pq()
        assert len(doc('.item')) == 10

    def test_filter_persistence(self):
        doc = self.get_pq(action='status')
        assert '?action=status' in (
            doc('ul.refinements').eq(0)('a').eq(1).attr('href')
        )

    def test_filter_updates(self):
        self.log_creates(10)
        self.log_updates(10)
        doc = self.get_pq()
        assert len(doc('.item')) == 20
        doc = self.get_pq(action='updates')
        assert len(doc('.item')) == 10

    def test_filter_status(self):
        self.log_creates(10)
        self.log_status(5)
        doc = self.get_pq()
        assert len(doc('.item')) == 15
        doc = self.get_pq(action='status')
        assert len(doc('.item')) == 5

    def test_filter_collections(self):
        self.log_creates(10)
        self.log_collection(3)
        doc = self.get_pq()
        assert len(doc('.item')) == 13
        doc = self.get_pq(action='collections')
        assert len(doc('.item')) == 3

    def test_filter_reviews(self):
        self.log_creates(10)
        self.log_rating(10)
        doc = self.get_pq()
        assert len(doc('.item')) == 20
        doc = self.get_pq(action='reviews')
        assert len(doc('.item')) == 10

    def test_pagination(self):
        self.log_rating(21)
        doc = self.get_pq()

        # 20 items on page 1.
        assert len(doc('.item')) == 20

        # 1 item on page 2
        doc = self.get_pq(page=2)
        assert len(doc('.item')) == 1

        # we have a pagination thingy
        assert len(doc('.pagination')) == 1
        assert doc('.listing-footer')

    def test_no_pagination(self):
        doc = self.get_pq()
        assert not doc('.listing-footer')

    def test_filter_addon(self):
        self.log_creates(10)
        self.log_creates(13, self.addon2)

        # We show everything without filters
        doc = self.get_pq()
        assert len(doc('.item')) == 20

        # We just show addon1
        doc = self.get_pq(addon=self.addon.id)
        assert len(doc('.item')) == 10

        # we just show addon2
        doc = self.get_pq(addon=self.addon2.id)
        assert len(doc('.item')) == 13

    def test_filter_addon_admin(self):
        """Admins should be able to see specific pages."""
        self.log_creates(10)
        assert self.client.login(email='admin@mozilla.com')
        r = self.get_response(addon=self.addon.id)
        assert r.status_code == 200

    def test_filter_addon_otherguy(self):
        """Make sure nobody else can see my precious add-on feed."""
        self.log_creates(10)
        assert self.client.login(email='clouserw@gmail.com')
        r = self.get_response(addon=self.addon.id)
        assert r.status_code == 403

    def test_rss(self):
        self.log_creates(5)
        # This will give us a new RssKey
        r = self.get_response()
        key = RssKey.objects.get()

        # Make sure we generate none-verbose uuid key by default.
        assert '-' not in key.key

        r = self.get_response(privaterss=key.key)
        assert r['content-type'] == 'application/rss+xml; charset=utf-8'
        assert '<title>Recent Changes for My Add-ons</title>' in r.content

    def test_rss_accepts_verbose(self):
        self.log_creates(5)
        r = self.get_response()
        key = RssKey.objects.get()
        r = self.get_response(privaterss=str(uuid.UUID(key.key)))
        assert r['content-type'] == 'application/rss+xml; charset=utf-8'
        assert '<title>Recent Changes for My Add-ons</title>' in r.content

    def test_rss_single(self):
        self.log_creates(5)
        self.log_creates(13, self.addon2)

        # This will give us a new RssKey
        r = self.get_response(addon=self.addon.id)
        key = RssKey.objects.get()
        r = self.get_response(privaterss=key.key)
        assert r['content-type'] == 'application/rss+xml; charset=utf-8'
        assert len(pq(r.content)('item')) == 5
        assert '<title>Recent Changes for %s</title>' % self.addon in r.content

    def test_rss_unlisted_addon(self):
        """Unlisted addon logs appear in the rss feed."""
        self.make_addon_unlisted(self.addon)
        self.log_creates(5)

        # This will give us a new RssKey
        self.get_response(addon=self.addon.id)
        key = RssKey.objects.get()
        response = self.get_response(privaterss=key.key)
        assert len(pq(response.content)('item')) == 6

    def test_logged_out(self):
        self.client.logout()
        response = self.get_response(follow=False)
        assert response.status_code == 302

    def test_xss_addon(self):
        self.addon.name = (
            "<script>alert('Buy more Diet Mountain Dew.')" '</script>'
        )
        self.addon.save()
        self.log_creates(1)
        doc = self.get_pq()
        assert len(doc('.item')) == 1
        assert '<script>' not in unicode(doc), 'XSS FTL'
        assert '&lt;script&gt;' in unicode(doc), 'XSS FTL'

    def test_xss_unlisted_addon(self):
        self.addon.name = (
            "<script>alert('Buy more Diet Mountain Dew.')" '</script>'
        )
        self.addon.save()
        self.make_addon_unlisted(self.addon)
        self.log_creates(1)
        doc = self.get_pq()
        assert len(doc('.item')) == 2
        assert '<script>' not in unicode(doc), 'XSS FTL'
        assert '&lt;script&gt;' in unicode(doc), 'XSS FTL'

    def test_xss_collections(self):
        self.log_collection(1, "<script>alert('v1@gra for u')</script>")
        doc = self.get_pq()
        assert len(doc('.item')) == 1
        assert '<script>' not in unicode(doc), 'XSS FTL'
        assert '&lt;script&gt;' in unicode(doc), 'XSS FTL'

    def test_xss_collections_unlisted_addon(self):
        self.make_addon_unlisted(self.addon)
        self.log_collection(1, "<script>alert('v1@gra for u')</script>")
        doc = self.get_pq()
        assert len(doc('.item')) == 2
        assert '<script>' not in unicode(doc), 'XSS FTL'
        assert '&lt;script&gt;' in unicode(doc), 'XSS FTL'

    def test_xss_tags(self):
        self.log_tag(1, "<script src='x.js'>")
        doc = self.get_pq()
        assert len(doc('.item')) == 1
        assert '<script' not in unicode(doc('.item')), 'XSS FTL'
        assert '&lt;script' in unicode(doc('.item')), 'XSS FTL'

    def test_xss_tags_unlisted_addon(self):
        self.make_addon_unlisted(self.addon)
        self.log_tag(1, "<script src='x.js'>")
        doc = self.get_pq()
        assert len(doc('.item')) == 2
        assert '<script' not in unicode(doc('.item')), 'XSS FTL'
        assert '&lt;script' in unicode(doc('.item')), 'XSS FTL'

    def test_xss_versions(self):
        self.log_updates(1, "<script src='x.js'>")
        doc = self.get_pq()
        assert len(doc('.item')) == 1
        assert '<script' not in unicode(doc('.item')), 'XSS FTL'
        assert '&lt;script' in unicode(doc('.item')), 'XSS FTL'

    def test_xss_versions_unlisted_addon(self):
        self.make_addon_unlisted(self.addon)
        self.log_updates(1, "<script src='x.js'>")
        doc = self.get_pq()
        assert len(doc('.item')) == 2
        assert '<script' not in unicode(doc('.item')), 'XSS FTL'
        assert '&lt;script' in unicode(doc('.item')), 'XSS FTL'

    def test_hidden(self):
        version = Version.objects.create(addon=self.addon)
        ActivityLog.create(amo.LOG.COMMENT_VERSION, self.addon, version)
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
