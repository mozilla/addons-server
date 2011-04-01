from datetime import datetime, timedelta

from nose.tools import eq_
import test_utils

import amo
from amo.cron import gc, remove_extra_cats
from amo.tasks import dedupe_approvals
from addons.models import Addon, AddonCategory, Category
from bandwagon.models import Collection
from cake.models import Session
from devhub.models import ActivityLog
from files.models import TestResult, TestResultCache
from stats.models import AddonShareCount, Contribution
from users.models import UserProfile
from versions.models import Version


class GarbageTest(test_utils.TestCase):
    fixtures = ['base/addon_59', 'base/garbage']

    def test_garbage_collection(self):
        "This fixture is expired data that should just get cleaned up."
        eq_(Collection.objects.all().count(), 1)
        eq_(Session.objects.all().count(), 1)
        eq_(ActivityLog.objects.all().count(), 1)
        eq_(TestResult.objects.all().count(), 1)
        eq_(TestResultCache.objects.all().count(), 1)
        eq_(AddonShareCount.objects.all().count(), 1)
        eq_(Contribution.objects.all().count(), 1)
        gc(test_result=False)
        eq_(Collection.objects.all().count(), 0)
        eq_(Session.objects.all().count(), 0)
        eq_(ActivityLog.objects.all().count(), 0)
        eq_(TestResultCache.objects.all().count(), 0)
        eq_(AddonShareCount.objects.all().count(), 0)
        eq_(Contribution.objects.all().count(), 0)

    def test_incomplete(self):
        a = Addon.objects.create(status=0, highest_status=0, type=1)
        a.created = datetime.today() - timedelta(days=5)
        a.save()
        assert Addon.objects.filter(status=0, highest_status=0)
        gc()
        assert not Addon.objects.filter(status=0, highest_status=0)


class RemoveExtraCatTest(test_utils.TestCase):
    fixtures = ['base/category']

    def setUp(self):
        self.misc = Category.objects.create(misc=True, name='misc',
                                            type=amo.ADDON_EXTENSION,
                                            application_id=amo.FIREFOX.id)
        self.regular = []
        for i in xrange(3):
            self.regular.append(Category.objects.create(
                name='normal_%d' % i, application_id=amo.FIREFOX.id,
                type=amo.ADDON_EXTENSION))
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

    def test_remove_others(self):
        eq_(self.addon.categories.count(), 0)
        AddonCategory.objects.create(addon=self.addon, category=self.misc)
        AddonCategory.objects.create(addon=self.addon,
                                     category=self.regular[0])
        eq_(self.addon.categories.count(), 2)
        remove_extra_cats()
        eq_(self.addon.categories.count(), 1)
        eq_(unicode(self.addon.categories.get().name), 'normal_0')

    def test_remove_extras(self):
        eq_(self.addon.categories.count(), 0)
        for cat in self.regular:
            AddonCategory.objects.create(addon=self.addon, category=cat)
        eq_(self.addon.categories.count(), 3)
        remove_extra_cats()
        eq_(self.addon.categories.count(), 2)

    def test_noop(self):
        eq_(self.addon.categories.count(), 0)
        for cat in self.regular[:2]:
            AddonCategory.objects.create(addon=self.addon, category=cat)
        eq_(self.addon.categories.count(), 2)
        remove_extra_cats()
        eq_(self.addon.categories.count(), 2)


class TestDedupeApprovals(test_utils.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        self.version = Version.objects.create(addon=self.addon)
        amo.set_user(UserProfile.objects.get(username='editor'))

    def test_dedupe(self):
        for x in range(0, 4):
            amo.log(amo.LOG.APPROVE_VERSION, self.addon, self.version)
        dedupe_approvals([self.addon.pk])
        eq_(ActivityLog.objects.for_addons(self.addon).count(), 1)

    def test_dedupe_mix(self):
        for x in range(0, 4):
            amo.log(amo.LOG.APPROVE_VERSION, self.addon, self.version)
        for x in range(0, 3):
            amo.log(amo.LOG.REJECT_VERSION, self.addon, self.version)
        for x in range(0, 5):
            amo.log(amo.LOG.APPROVE_VERSION, self.addon, self.version)
        dedupe_approvals([self.addon.pk])
        eq_(ActivityLog.objects.for_addons(self.addon).count(), 3)

    def test_dedupe_date(self):
        # Test that a log spanning
        old = amo.log(amo.LOG.APPROVE_VERSION, self.addon, self.version)
        old.update(created=datetime.today() - timedelta(days=1))
        amo.log(amo.LOG.APPROVE_VERSION, self.addon, self.version)
        dedupe_approvals([self.addon.pk])
        eq_(ActivityLog.objects.for_addons(self.addon).count(), 2)
