from datetime import datetime, timedelta
from uuid import UUID

from mock import Mock
from pyquery import PyQuery as pq

from olympia import amo, core
from olympia.activity.models import (
    MAX_TOKEN_USE_COUNT, ActivityLog, ActivityLogToken, AddonLog)
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import (
    TestCase, addon_factory, user_factory, version_factory)
from olympia.bandwagon.models import Collection
from olympia.ratings.models import Rating
from olympia.tags.models import Tag
from olympia.users.models import UserProfile
from olympia.versions.models import Version


class TestActivityLogToken(TestCase):
    def setUp(self):
        super(TestActivityLogToken, self).setUp()
        self.addon = addon_factory()
        self.version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        self.version.update(created=self.days_ago(1))
        self.user = user_factory()
        self.token = ActivityLogToken.objects.create(
            version=self.version, user=self.user)

    def test_uuid_is_automatically_created(self):
        assert self.token.uuid
        assert isinstance(self.token.uuid, UUID)

    def test_validity_use_expiry(self):
        assert self.token.use_count == 0
        self.token.increment_use()
        assert self.token.use_count == 1
        assert not self.token.is_expired()
        self.token.expire()
        assert self.token.use_count == MAX_TOKEN_USE_COUNT
        # Being expired is invalid too.
        assert self.token.is_expired()
        # But the version is still the latest version.
        assert self.version == self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        assert not self.token.is_valid()

    def test_increment_use(self):
        assert self.token.use_count == 0
        self.token.increment_use()
        assert self.token.use_count == 1
        token_from_db = ActivityLogToken.objects.get(
            version=self.version, user=self.user)
        assert token_from_db.use_count == 1

    def test_validity_version_out_of_date(self):
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED)
        # The token isn't expired.
        assert not self.token.is_expired()
        # But is invalid, because the version isn't the latest version.
        assert not self.token.is_valid()

    def test_validity_still_valid_if_new_version_in_different_channel(self):
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert self.version == self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)

        # The token isn't expired.
        assert not self.token.is_expired()
        # It's also still valid, since our version is still the latest listed
        # one.
        assert self.token.is_valid()

    def test_rejected_version_still_valid(self):
        for file_ in self.version.all_files:
            file_.update(status=amo.STATUS_DISABLED)
        # Being a rejected version shouldn't mean you can't reply
        assert self.token.is_valid()


class TestActivityLog(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestActivityLog, self).setUp()
        self.user = UserProfile.objects.create(username='yolo')
        self.request = Mock()
        self.request.user = self.user
        core.set_user(self.user)

    def tearDown(self):
        core.set_user(None)
        super(TestActivityLog, self).tearDown()

    def test_basic(self):
        addon = Addon.objects.get()
        ActivityLog.create(amo.LOG.CREATE_ADDON, addon)
        entries = ActivityLog.objects.for_addons(addon)
        assert len(entries) == 1
        assert entries[0].arguments[0] == addon
        for x in ('Delicious Bookmarks', 'was created.'):
            assert x in unicode(entries[0])

    def test_no_user(self):
        core.set_user(None)
        count = ActivityLog.objects.count()
        ActivityLog.create(amo.LOG.CUSTOM_TEXT, 'hi')
        assert count == ActivityLog.objects.count()

    def test_pseudo_objects(self):
        """
        If we give an argument of (Addon, 3615) ensure we get
        Addon.objects.get(pk=3615).
        """
        activity_log = ActivityLog()
        activity_log.arguments = [(Addon, 3615)]
        assert activity_log.arguments[0] == Addon.objects.get(pk=3615)

    def test_addon_logging_pseudo(self):
        """
        If we are given (Addon, 3615) it should log in the AddonLog as well.
        """
        addon = Addon.objects.get()
        ActivityLog.create(amo.LOG.CREATE_ADDON, (Addon, addon.id))
        assert AddonLog.objects.count() == 1

    def test_addon_log(self):
        addon = Addon.objects.get()
        ActivityLog.create(amo.LOG.CREATE_ADDON, (Addon, addon.id))
        entries = ActivityLog.objects.for_addons(addon)
        assert len(entries) == 1
        assert addon.get_url_path() in unicode(entries[0])

    def test_addon_log_unlisted_addon(self):
        addon = Addon.objects.get()
        # Get the url before the addon is changed to unlisted.
        url_path = addon.get_url_path()
        self.make_addon_unlisted(addon)
        # Delete the status change log entry from making versions unlisted.
        ActivityLog.objects.for_addons(addon).delete()
        ActivityLog.create(amo.LOG.CREATE_ADDON, (Addon, addon.id))
        entries = ActivityLog.objects.for_addons(addon)
        assert len(entries) == 1
        assert url_path not in unicode(entries[0])

    def test_fancy_rendering(self):
        """HTML for Rating, and Collection."""
        activity_log = ActivityLog.objects.create(action=amo.LOG.ADD_RATING.id)
        user = UserProfile.objects.create()
        rating = Rating.objects.create(user=user, addon_id=3615)
        activity_log.arguments = [activity_log, rating]
        assert '>Review</a> for None written.' in activity_log.to_string()
        activity_log.action = amo.LOG.ADD_TO_COLLECTION.id
        activity_log.arguments = [activity_log, Collection.objects.create()]
        assert 'None added to <a href="/' in activity_log.to_string()

    def test_bad_arguments(self):
        activity_log = ActivityLog()
        activity_log.arguments = []
        activity_log.action = amo.LOG.ADD_USER_WITH_ROLE.id
        assert activity_log.to_string() == 'Something magical happened.'

    def test_json_failboat(self):
        addon = Addon.objects.get()
        ActivityLog.create(amo.LOG.CREATE_ADDON, addon)
        entry = ActivityLog.objects.get()
        entry._arguments = 'failboat?'
        entry.save()
        assert entry.arguments is None

    def test_arguments_old_reviews_app(self):
        addon = Addon.objects.get()
        rating = Rating.objects.create(
            addon=addon, user=self.user, user_responsible=self.user, rating=5)
        activity = ActivityLog.objects.latest('pk')
        # Override _arguments to use reviews.review instead of ratings.rating,
        # as old data already present in the db would use.
        activity._arguments = (
            u'[{"addons.addon": %d}, {"reviews.review": %d}]' % (
                addon.pk, rating.pk))
        assert activity.arguments == [addon, rating]

    def test_no_arguments(self):
        ActivityLog.create(amo.LOG.CUSTOM_HTML)
        entry = ActivityLog.objects.get()
        assert entry.arguments == []

    def test_output(self):
        ActivityLog.create(amo.LOG.CUSTOM_TEXT, 'hi there')
        entry = ActivityLog.objects.get()
        assert unicode(entry) == 'hi there'

    def test_user_log(self):
        request = self.request
        ActivityLog.create(amo.LOG.CUSTOM_TEXT, 'hi there')
        entries = ActivityLog.objects.for_user(request.user)
        assert len(entries) == 1

    def test_user_log_as_argument(self):
        """
        Tests that a user that has something done to them gets into the user
        log.
        """
        user = UserProfile(username='Marlboro Manatee')
        user.save()
        ActivityLog.create(amo.LOG.ADD_USER_WITH_ROLE,
                           user, 'developer', Addon.objects.get())
        entries = ActivityLog.objects.for_user(self.request.user)
        assert len(entries) == 1
        entries = ActivityLog.objects.for_user(user)
        assert len(entries) == 1

    def test_version_log(self):
        version = Version.objects.all()[0]
        ActivityLog.create(amo.LOG.REJECT_VERSION, version.addon, version,
                           user=self.request.user)
        entries = ActivityLog.objects.for_version(version)
        assert len(entries) == 1
        assert version.get_url_path() in unicode(entries[0])

    def test_version_log_unlisted_addon(self):
        version = Version.objects.all()[0]
        # Get the url before the addon is changed to unlisted.
        url_path = version.get_url_path()
        self.make_addon_unlisted(version.addon)
        ActivityLog.create(amo.LOG.REJECT_VERSION, version.addon, version,
                           user=self.request.user)
        entries = ActivityLog.objects.for_version(version)
        assert len(entries) == 1
        assert url_path not in unicode(entries[0])

    def test_version_log_transformer(self):
        addon = Addon.objects.get()
        version = addon.current_version
        ActivityLog.create(amo.LOG.REJECT_VERSION, addon, version,
                           user=self.request.user)

        version_two = Version(addon=addon, license=version.license,
                              version='1.2.3')
        version_two.save()

        ActivityLog.create(amo.LOG.REJECT_VERSION, addon, version_two,
                           user=self.request.user)

        versions = (Version.objects.filter(addon=addon).order_by('-created')
                                   .transform(Version.transformer_activity))

        assert len(versions[0].all_activity) == 1
        assert len(versions[1].all_activity) == 1

    def test_xss_arguments_and_escaping(self):
        addon = Addon.objects.get()
        addon.name = 'Delicious <script src="x.js">Bookmarks'
        addon.save()
        addon = addon.reload()
        au = AddonUser(addon=addon, user=self.user)
        ActivityLog.create(amo.LOG.CHANGE_USER_WITH_ROLE, au.user,
                           au.get_role_display(), addon)
        log = ActivityLog.objects.get()

        log_expected = ('yolo role changed to Owner for <a href="/en-US/'
                        'firefox/addon/a3615/">Delicious &lt;script src='
                        '&#34;x.js&#34;&gt;Bookmarks</a>.')
        assert log.to_string() == log_expected

        rendered = amo.utils.from_string('<p>{{ log }}</p>').render(
            {'log': log})
        assert rendered == '<p>%s</p>' % log_expected

    def test_tag_no_match(self):
        addon = Addon.objects.get()
        tag = Tag.objects.create(tag_text='http://foo.com')
        ActivityLog.create(amo.LOG.ADD_TAG, addon, tag)
        log = ActivityLog.objects.get()
        text = amo.utils.from_string('<p>{{ log }}</p>').render({'log': log})
        # There should only be one a, the link to the addon, but no tag link.
        assert len(pq(text)('a')) == 1

    def test_change_status(self):
        addon = Addon.objects.get()
        log = ActivityLog.create(
            amo.LOG.CHANGE_STATUS, addon, amo.STATUS_PUBLIC)
        expected = ('<a href="/en-US/firefox/addon/a3615/">'
                    'Delicious Bookmarks</a> status changed to Approved.')
        assert unicode(log) == expected

        log.arguments = [amo.STATUS_DISABLED, addon]
        expected = ('<a href="/en-US/firefox/addon/a3615/">'
                    'Delicious Bookmarks</a> status changed to '
                    'Disabled by Mozilla.')
        assert unicode(log) == expected

        log.arguments = [addon, amo.STATUS_REJECTED]
        expected = ('<a href="/en-US/firefox/addon/a3615/">'
                    'Delicious Bookmarks</a> status changed to Rejected.')
        assert unicode(log) == expected

        log.arguments = [addon, 666]
        expected = ('<a href="/en-US/firefox/addon/a3615/">'
                    'Delicious Bookmarks</a> status changed to 666.')
        assert unicode(log) == expected

        log.arguments = [addon, 'Some String']
        expected = ('<a href="/en-US/firefox/addon/a3615/">'
                    'Delicious Bookmarks</a> status changed to Some String.')
        assert unicode(log) == expected


class TestActivityLogCount(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestActivityLogCount, self).setUp()
        now = datetime.now()
        bom = datetime(now.year, now.month, 1)
        self.lm = bom - timedelta(days=1)
        self.user = UserProfile.objects.get()
        core.set_user(self.user)

    def add_approve_logs(self, count):
        for x in range(0, count):
            ActivityLog.create(amo.LOG.APPROVE_VERSION, Addon.objects.get())

    def test_not_review_count(self):
        ActivityLog.create(amo.LOG.EDIT_VERSION, Addon.objects.get())
        assert len(ActivityLog.objects.monthly_reviews()) == 0

    def test_review_count(self):
        ActivityLog.create(amo.LOG.APPROVE_VERSION, Addon.objects.get())
        result = ActivityLog.objects.monthly_reviews()
        assert len(result) == 1
        assert result[0]['approval_count'] == 1
        assert result[0]['user'] == self.user.pk

    def test_review_count_few(self):
        self.add_approve_logs(5)
        result = ActivityLog.objects.monthly_reviews()
        assert len(result) == 1
        assert result[0]['approval_count'] == 5

    def test_review_last_month(self):
        log = ActivityLog.create(amo.LOG.APPROVE_VERSION,
                                 Addon.objects.get())
        log.update(created=self.lm)
        assert len(ActivityLog.objects.monthly_reviews()) == 0

    def test_not_total(self):
        ActivityLog.create(amo.LOG.EDIT_VERSION, Addon.objects.get())
        assert len(ActivityLog.objects.total_ratings()) == 0

    def test_total_few(self):
        self.add_approve_logs(5)
        result = ActivityLog.objects.total_ratings()
        assert len(result) == 1
        assert result[0]['approval_count'] == 5

    def test_total_last_month(self):
        log = ActivityLog.create(amo.LOG.APPROVE_VERSION,
                                 Addon.objects.get())
        log.update(created=self.lm)
        result = ActivityLog.objects.total_ratings()
        assert len(result) == 1
        assert result[0]['approval_count'] == 1
        assert result[0]['user'] == self.user.pk

    def test_total_ratings_user_position(self):
        self.add_approve_logs(5)
        result = ActivityLog.objects.total_ratings_user_position(self.user)
        assert result == 1
        user = UserProfile.objects.create(email="no@mozil.la")
        result = ActivityLog.objects.total_ratings_user_position(user)
        assert result is None

    def test_monthly_reviews_user_position(self):
        self.add_approve_logs(5)
        result = ActivityLog.objects.monthly_reviews_user_position(self.user)
        assert result == 1
        user = UserProfile.objects.create(email="no@mozil.la")
        result = ActivityLog.objects.monthly_reviews_user_position(user)
        assert result is None

    def test_user_approve_reviews(self):
        self.add_approve_logs(3)
        other = UserProfile.objects.create(email="no@mozil.la", username="o")
        core.set_user(other)
        self.add_approve_logs(2)
        result = ActivityLog.objects.user_approve_reviews(self.user).count()
        assert result == 3
        result = ActivityLog.objects.user_approve_reviews(other).count()
        assert result == 2
        another = UserProfile.objects.create(
            email="no@mtrala.la", username="a")
        result = ActivityLog.objects.user_approve_reviews(another).count()
        assert result == 0

    def test_current_month_user_approve_reviews(self):
        self.add_approve_logs(3)
        ActivityLog.objects.update(created=self.days_ago(40))
        self.add_approve_logs(2)
        result = ActivityLog.objects.current_month_user_approve_reviews(
            self.user).count()
        assert result == 2

    def test_log_admin(self):
        ActivityLog.create(amo.LOG.OBJECT_EDITED, Addon.objects.get())
        assert len(ActivityLog.objects.admin_events()) == 1
        assert len(ActivityLog.objects.for_developer()) == 0

    def test_log_not_admin(self):
        ActivityLog.create(amo.LOG.EDIT_VERSION, Addon.objects.get())
        assert len(ActivityLog.objects.admin_events()) == 0
        assert len(ActivityLog.objects.for_developer()) == 1
