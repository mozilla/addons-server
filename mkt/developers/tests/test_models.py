from datetime import datetime, timedelta

from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from mkt.developers.models import ActivityLog
from files.models import File
from users.models import UserProfile
from versions.models import Version


class TestVersion(amo.tests.TestCase):
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


class TestActivityLogCount(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        now = datetime.now()
        bom = datetime(now.year, now.month, 1)
        self.lm = bom - timedelta(days=1)
        self.user = UserProfile.objects.get()
        amo.set_user(self.user)

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
        for x in range(0, 5):
            amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
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
        for x in range(0, 5):
            amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
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

    def test_log_admin(self):
        amo.log(amo.LOG['OBJECT_EDITED'], Addon.objects.get())
        eq_(len(ActivityLog.objects.admin_events()), 1)
        eq_(len(ActivityLog.objects.for_developer()), 0)

    def test_log_not_admin(self):
        amo.log(amo.LOG['EDIT_VERSION'], Addon.objects.get())
        eq_(len(ActivityLog.objects.admin_events()), 0)
        eq_(len(ActivityLog.objects.for_developer()), 1)
