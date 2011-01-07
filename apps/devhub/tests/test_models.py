import jingo
import test_utils
from nose.tools import eq_
from mock import Mock
from pyquery import PyQuery as pq

import amo
from addons.models import Addon, AddonUser
from bandwagon.models import Collection
from devhub.models import ActivityLog
from tags.models import Tag
from files.models import File
from reviews.models import Review
from users.models import UserProfile
from versions.models import Version


class TestActivityLog(test_utils.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        u = UserProfile(username='<script src="x.js">')
        u.save()
        self.request = Mock()
        self.request.amo_user = self.user = u
        amo.set_user(u)

    def tearDown(self):
        amo.set_user(None)

    def test_basic(self):
        a = Addon.objects.get()
        amo.log(amo.LOG['CREATE_ADDON'], a)
        entries = ActivityLog.objects.for_addons(a)
        eq_(len(entries), 1)
        eq_(entries[0].arguments[0], a)
        for x in ('Delicious Bookmarks', 'was created.'):
            assert x in unicode(entries[0])

    def test_no_user(self):
        amo.set_user(None)
        count = ActivityLog.objects.count()
        amo.log(amo.LOG.CUSTOM_TEXT, 'hi')
        eq_(count, ActivityLog.objects.count())

    def test_pseudo_objects(self):
        """
        If we give an argument of (Addon, 3615) ensure we get
        Addon.objects.get(pk=3615).
        """
        a = ActivityLog()
        a.arguments = [(Addon, 3615)]
        eq_(a.arguments[0], Addon.objects.get(pk=3615))

    def test_fancy_rendering(self):
        """HTML for Review, and Collection."""
        a = ActivityLog.objects.create(action=amo.LOG.ADD_REVIEW.id)
        u = UserProfile.objects.create()
        r = Review.objects.create(user=u, addon_id=3615)
        a.arguments = [a, r]
        assert '>Review</a> for None written.' in a.to_string()
        a.action = amo.LOG.ADD_TO_COLLECTION.id
        a.arguments = [a, Collection.objects.create()]
        assert 'None added to <a href="/' in a.to_string()

    def test_bad_arguments(self):
        a = ActivityLog()
        a.arguments = []
        a.action = amo.LOG.ADD_USER_WITH_ROLE.id
        eq_(a.to_string(), 'Something magical happened.')

    def test_json_failboat(self):
        a = Addon.objects.get()
        amo.log(amo.LOG['CREATE_ADDON'], a)
        entry = ActivityLog.objects.get()
        entry._arguments = 'failboat?'
        entry.save()
        eq_(entry.arguments, None)

    def test_no_arguments(self):
        amo.log(amo.LOG['CUSTOM_HTML'])
        entry = ActivityLog.objects.get()
        eq_(entry.arguments, [])

    def test_output(self):
        amo.log(amo.LOG['CUSTOM_TEXT'], 'hi there')
        entry = ActivityLog.objects.get()
        eq_(unicode(entry), 'hi there')

    def test_user_log(self):
        request = self.request
        amo.log(amo.LOG['CUSTOM_TEXT'], 'hi there')
        entries = ActivityLog.objects.for_user(request.amo_user)
        eq_(len(entries), 1)

    def test_user_log_as_argument(self):
        """
        Tests that a user that has something done to them gets into the user
        log.
        """
        u = UserProfile(username='Marlboro Manatee')
        u.save()
        amo.log(amo.LOG['ADD_USER_WITH_ROLE'],
                u, 'developer', Addon.objects.get())
        entries = ActivityLog.objects.for_user(self.request.amo_user)
        eq_(len(entries), 1)
        entries = ActivityLog.objects.for_user(u)
        eq_(len(entries), 1)

    def test_xss_arguments(self):
        addon = Addon.objects.get()
        au = AddonUser(addon=addon, user=self.user)
        amo.log(amo.LOG.CHANGE_USER_WITH_ROLE, au.user, au.get_role_display(),
                addon)
        log = ActivityLog.objects.get()
        eq_(log.to_string(),
            u'&lt;script src=&#34;x.js&#34;&gt; role changed to Owner for '
            '<a href="/en-US/firefox/addon/a3615/">Delicious Bookmarks</a>.')

    def test_jinja_escaping(self):
        addon = Addon.objects.get()
        au = AddonUser(addon=addon, user=self.user)
        amo.log(amo.LOG.CHANGE_USER_WITH_ROLE, au.user, au.get_role_display(),
                addon)
        log = ActivityLog.objects.get()
        eq_(jingo.env.from_string('<p>{{ log }}</p>').render(log=log),
            '<p>&lt;script src=&#34;x.js&#34;&gt; role changed to Owner for <a'
            ' href="/en-US/firefox/addon/a3615/">Delicious Bookmarks</a>.</p>')

    def test_tag_no_match(self):
        addon = Addon.objects.get()
        tag = Tag.objects.create(tag_text='http://foo.com')
        amo.log(amo.LOG.ADD_TAG, addon, tag)
        log = ActivityLog.objects.get()
        text = jingo.env.from_string('<p>{{ log }}</p>').render(log=log)
        # There should only be one a, the link to the addon, but no tag link.
        eq_(len(pq(text)('a')), 1)


class TestVersion(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615',
                'base/thunderbird', 'base/platforms']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.version = Version.objects.get(pk=81551)
        self.file = File.objects.get(pk=67442)

    def test_version_delete_status_null(self):
        self.version.delete()
        eq_(self.addon.versions.count(), 0)
        eq_(Addon.objects.get(pk=3615).status, amo.STATUS_NULL)

    def _extra_version_and_file(self, status):
        version = Version.objects.get(pk=81551)

        version_two = Version(addon=self.addon,
                              license=version.license,
                              version='1.2.3')
        version_two.save()

        file_two = File(status=status, version=version_two)
        file_two.save()
        return version_two, file_two

    def test_version_delete_status(self):
        self._extra_version_and_file(amo.STATUS_PUBLIC)
        self.addon.status = amo.STATUS_BETA
        self.addon.save()

        self.version.delete()
        eq_(self.addon.versions.count(), 1)
        eq_(Addon.objects.get(id=3615).status, amo.STATUS_BETA)

    def test_version_delete_status_unreviewed(self):
        self._extra_version_and_file(amo.STATUS_BETA)

        self.version.delete()
        eq_(self.addon.versions.count(), 1)
        eq_(Addon.objects.get(id=3615).status, amo.STATUS_UNREVIEWED)

    def test_file_delete_status_null(self):
        eq_(self.addon.versions.count(), 1)
        self.file.delete()
        eq_(self.addon.versions.count(), 1)
        eq_(Addon.objects.get(pk=3615).status, amo.STATUS_NULL)

    def test_file_delete_status_null_multiple(self):
        version_two, file_two = self._extra_version_and_file(amo.STATUS_NULL)
        self.file.delete()
        eq_(self.addon.status, amo.STATUS_PUBLIC)
        file_two.delete()
        eq_(self.addon.status, amo.STATUS_NULL)
