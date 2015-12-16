from datetime import datetime, timedelta
from os import path

from django.core.urlresolvers import reverse

import jingo
from nose.tools import eq_
from mock import Mock
from pyquery import PyQuery as pq

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.addons.models import Addon, AddonUser
from olympia.bandwagon.models import Collection
from olympia.devhub.models import ActivityLog, AddonLog, BlogPost
from olympia.tags.models import Tag
from olympia.files.models import File
from olympia.reviews.models import Review
from olympia.users.models import UserProfile
from olympia.versions.models import Version


TESTS_DIR = path.dirname(path.abspath(__file__))
ATTACHMENTS_DIR = path.join(TESTS_DIR, 'attachments')


class TestActivityLog(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestActivityLog, self).setUp()
        u = UserProfile.objects.create(username='yolo')
        self.request = Mock()
        self.request.user = self.user = u
        amo.set_user(u)

    def tearDown(self):
        amo.set_user(None)
        super(TestActivityLog, self).tearDown()

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

    def test_addon_logging_pseudo(self):
        """
        If we are given (Addon, 3615) it should log in the AddonLog as well.
        """
        a = Addon.objects.get()
        amo.log(amo.LOG.CREATE_ADDON, (Addon, a.id))
        eq_(AddonLog.objects.count(), 1)

    def test_addon_log(self):
        addon = Addon.objects.get()
        amo.log(amo.LOG.CREATE_ADDON, (Addon, addon.id))
        entries = ActivityLog.objects.for_addons(addon)
        assert len(entries) == 1
        assert addon.get_url_path() in unicode(entries[0])

    def test_addon_log_unlisted_addon(self):
        addon = Addon.objects.get()
        # Get the url before the addon is changed to unlisted.
        url_path = addon.get_url_path()
        addon.update(is_listed=False)
        amo.log(amo.LOG.CREATE_ADDON, (Addon, addon.id))
        entries = ActivityLog.objects.for_addons(addon)
        assert len(entries) == 1
        assert url_path not in unicode(entries[0])

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
        entries = ActivityLog.objects.for_user(request.user)
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
        entries = ActivityLog.objects.for_user(self.request.user)
        eq_(len(entries), 1)
        entries = ActivityLog.objects.for_user(u)
        eq_(len(entries), 1)

    def test_version_log(self):
        version = Version.objects.all()[0]
        amo.log(amo.LOG.REJECT_VERSION, version.addon, version,
                user=self.request.user)
        entries = ActivityLog.objects.for_version(version)
        assert len(entries) == 1
        assert version.get_url_path() in unicode(entries[0])

    def test_version_log_unlisted_addon(self):
        version = Version.objects.all()[0]
        addon = version.addon
        # Get the url before the addon is changed to unlisted.
        url_path = version.get_url_path()
        addon.update(is_listed=False)
        amo.log(amo.LOG.REJECT_VERSION, version.addon, version,
                user=self.request.user)
        entries = ActivityLog.objects.for_version(version)
        assert len(entries) == 1
        assert url_path not in unicode(entries[0])

    def test_version_log_transformer(self):
        addon = Addon.objects.get()
        version = addon.latest_version
        amo.log(amo.LOG.REJECT_VERSION, addon, version,
                user=self.request.user)

        version_two = Version(addon=addon, license=version.license,
                              version='1.2.3')
        version_two.save()

        amo.log(amo.LOG.REJECT_VERSION, addon, version_two,
                user=self.request.user)

        versions = (Version.objects.filter(addon=addon).order_by('-created')
                                   .transform(Version.transformer_activity))

        eq_(len(versions[0].all_activity), 1)
        eq_(len(versions[1].all_activity), 1)

    def test_xss_arguments_and_escaping(self):
        addon = Addon.objects.get()
        addon.name = 'Delicious <script src="x.js">Bookmarks'
        addon.save()
        addon = addon.reload()
        au = AddonUser(addon=addon, user=self.user)
        amo.log(amo.LOG.CHANGE_USER_WITH_ROLE, au.user, au.get_role_display(),
                addon)
        log = ActivityLog.objects.get()

        log_expected = ('yolo role changed to Owner for <a href="/en-US/'
                        'firefox/addon/a3615/">Delicious &lt;script src='
                        '&#34;x.js&#34;&gt;Bookmarks</a>.')
        eq_(log.to_string(), log_expected)
        eq_(jingo.env.from_string('<p>{{ log }}</p>').render({'log': log}),
            '<p>%s</p>' % log_expected)

    def test_tag_no_match(self):
        addon = Addon.objects.get()
        tag = Tag.objects.create(tag_text='http://foo.com')
        amo.log(amo.LOG.ADD_TAG, addon, tag)
        log = ActivityLog.objects.get()
        text = jingo.env.from_string('<p>{{ log }}</p>').render({'log': log})
        # There should only be one a, the link to the addon, but no tag link.
        eq_(len(pq(text)('a')), 1)

    def test_beta_signed_events_validation_passed(self):
        addon = Addon.objects.get()
        file_ = addon.versions.first().files.first()
        # Signed beta file which passed validation.
        amo.log(amo.LOG.BETA_SIGNED_VALIDATION_PASSED, file_)
        log = ActivityLog.objects.beta_signed_events().first().to_string()
        link = pq(log)('a')
        assert len(link) == 1
        assert link[0].attrib['href'] == reverse('files.list', args=[file_.pk])
        msg = '<a href="{0}">{1}</a> (validation passed) was signed.'.format(
            reverse('files.list', args=[file_.pk]), file_.filename)
        assert log == msg

    def test_beta_signed_events_validation_failed(self):
        addon = Addon.objects.get()
        file_ = addon.versions.first().files.first()
        # Signed beta file which failed validation.
        amo.log(amo.LOG.BETA_SIGNED_VALIDATION_FAILED, file_)
        log = ActivityLog.objects.beta_signed_events().first().to_string()
        link = pq(log)('a')
        assert len(link) == 1
        assert link[0].attrib['href'] == reverse('files.list', args=[file_.pk])
        msg = '<a href="{0}">{1}</a> (validation failed) was signed.'.format(
            reverse('files.list', args=[file_.pk]), file_.filename)
        assert log == msg


class TestVersion(TestCase):
    fixtures = ['base/users', 'base/addon_3615', 'base/thunderbird']

    def setUp(self):
        super(TestVersion, self).setUp()
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


class TestActivityLogCount(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestActivityLogCount, self).setUp()
        now = datetime.now()
        bom = datetime(now.year, now.month, 1)
        self.lm = bom - timedelta(days=1)
        self.user = UserProfile.objects.get()
        amo.set_user(self.user)

    def add_approve_logs(self, count):
        for x in range(0, count):
            amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())

    def test_not_review_count(self):
        amo.log(amo.LOG['EDIT_VERSION'], Addon.objects.get())
        eq_(len(ActivityLog.objects.monthly_reviews()), 0)

    def test_review_count(self):
        amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
        result = ActivityLog.objects.monthly_reviews()
        eq_(len(result), 1)
        eq_(result[0]['approval_count'], 1)
        eq_(result[0]['user'], self.user.pk)

    def test_review_count_few(self):
        self.add_approve_logs(5)
        result = ActivityLog.objects.monthly_reviews()
        eq_(len(result), 1)
        eq_(result[0]['approval_count'], 5)

    def test_review_last_month(self):
        log = amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
        log.update(created=self.lm)
        eq_(len(ActivityLog.objects.monthly_reviews()), 0)

    def test_not_total(self):
        amo.log(amo.LOG['EDIT_VERSION'], Addon.objects.get())
        eq_(len(ActivityLog.objects.total_reviews()), 0)

    def test_total_few(self):
        self.add_approve_logs(5)
        result = ActivityLog.objects.total_reviews()
        eq_(len(result), 1)
        eq_(result[0]['approval_count'], 5)

    def test_total_last_month(self):
        log = amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
        log.update(created=self.lm)
        result = ActivityLog.objects.total_reviews()
        eq_(len(result), 1)
        eq_(result[0]['approval_count'], 1)
        eq_(result[0]['user'], self.user.pk)

    def test_total_reviews_user_position(self):
        self.add_approve_logs(5)
        result = ActivityLog.objects.total_reviews_user_position(self.user)
        eq_(result, 1)
        user = UserProfile.objects.create(email="no@mozil.la")
        result = ActivityLog.objects.total_reviews_user_position(user)
        eq_(result, None)

    def test_monthly_reviews_user_position(self):
        self.add_approve_logs(5)
        result = ActivityLog.objects.monthly_reviews_user_position(self.user)
        eq_(result, 1)
        user = UserProfile.objects.create(email="no@mozil.la")
        result = ActivityLog.objects.monthly_reviews_user_position(user)
        eq_(result, None)

    def test_user_approve_reviews(self):
        self.add_approve_logs(3)
        other = UserProfile.objects.create(email="no@mozil.la", username="o")
        amo.set_user(other)
        self.add_approve_logs(2)
        result = ActivityLog.objects.user_approve_reviews(self.user).count()
        eq_(result, 3)
        result = ActivityLog.objects.user_approve_reviews(other).count()
        eq_(result, 2)
        another = UserProfile.objects.create(
            email="no@mtrala.la", username="a")
        result = ActivityLog.objects.user_approve_reviews(another).count()
        eq_(result, 0)

    def test_current_month_user_approve_reviews(self):
        self.add_approve_logs(3)
        ActivityLog.objects.update(created=self.days_ago(40))
        self.add_approve_logs(2)
        result = ActivityLog.objects.current_month_user_approve_reviews(
            self.user).count()
        eq_(result, 2)

    def test_log_admin(self):
        amo.log(amo.LOG['OBJECT_EDITED'], Addon.objects.get())
        eq_(len(ActivityLog.objects.admin_events()), 1)
        eq_(len(ActivityLog.objects.for_developer()), 0)

    def test_log_not_admin(self):
        amo.log(amo.LOG['EDIT_VERSION'], Addon.objects.get())
        eq_(len(ActivityLog.objects.admin_events()), 0)
        eq_(len(ActivityLog.objects.for_developer()), 1)


class TestBlogPosts(TestCase):

    def test_blog_posts(self):
        BlogPost.objects.create(title='hi')
        bp = BlogPost.objects.all()
        eq_(bp.count(), 1)
        eq_(bp[0].title, "hi")
