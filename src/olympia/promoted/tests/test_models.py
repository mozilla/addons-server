from django.conf import settings

from olympia import amo, core
from olympia.amo.tests import TestCase, addon_factory, user_factory, version_factory
from olympia.constants import applications, promoted
from olympia.promoted.models import (
    PromotedAddon,
    PromotedApproval,
)
from olympia.versions.utils import get_review_due_date


class TestPromotedAddon(TestCase):
    def setUp(self):
        self.task_user = user_factory(pk=settings.TASK_USER_ID)

    def test_basic(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.LINE.id
        )
        assert promoted_addon.group == promoted.LINE
        assert promoted_addon.application_id is None
        assert promoted_addon.all_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]

        promoted_addon.update(application_id=applications.FIREFOX.id)
        assert promoted_addon.all_applications == [applications.FIREFOX]

    def test_is_approved_applications(self):
        addon = addon_factory()
        promoted_addon = PromotedAddon.objects.create(
            addon=addon, group_id=promoted.LINE.id
        )
        assert addon.promotedaddon
        # Just having the PromotedAddon instance isn't enough
        assert addon.promotedaddon.approved_applications == []

        # the current version needs to be approved also
        promoted_addon.approve_for_version(addon.current_version)
        addon.reload()
        assert addon.promotedaddon.approved_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]

        # but not if it's for a different type of promotion
        promoted_addon.update(group_id=promoted.SPOTLIGHT.id)
        assert addon.promotedaddon.approved_applications == []
        # unless that group has an approval too
        PromotedApproval.objects.create(
            version=addon.current_version,
            group_id=promoted.SPOTLIGHT.id,
            application_id=applications.FIREFOX.id,
        )
        addon.reload()
        assert addon.promotedaddon.approved_applications == [applications.FIREFOX]

        # for promoted groups that don't require pre-review though, there isn't
        # a per version approval, so a current_version is sufficient and all
        # applications are seen as approved.
        promoted_addon.update(group_id=promoted.STRATEGIC.id)
        assert addon.promotedaddon.approved_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]

    def test_auto_approves_addon_when_saved_for_immediate_approval(self):
        # empty case with no group set
        promo = PromotedAddon.objects.create(
            addon=addon_factory(), application_id=amo.FIREFOX.id
        )
        assert promo.group == promoted.NOT_PROMOTED
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()

        # first test with a group.immediate_approval == False
        promo.group_id = promoted.RECOMMENDED.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group() == promoted.NOT_PROMOTED

        # then with a group thats immediate_approval == True
        promo.group_id = promoted.SPOTLIGHT.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == [amo.FIREFOX]
        assert PromotedApproval.objects.count() == 1
        assert promo.addon.promoted_group() == promoted.SPOTLIGHT

        # test the edge case where the application was changed afterwards
        promo.application_id = 0
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == [amo.FIREFOX, amo.ANDROID]
        assert PromotedApproval.objects.count() == 2

    def test_addon_flagged_for_human_review_when_saved(self):
        # empty case with no group set
        promo = PromotedAddon.objects.create(
            addon=addon_factory(), application_id=amo.FIREFOX.id
        )
        listed_ver = promo.addon.current_version
        # throw in an unlisted version too
        unlisted_ver = version_factory(addon=promo.addon, channel=amo.CHANNEL_UNLISTED)
        assert promo.group == promoted.NOT_PROMOTED
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()

        # first test with a group.flag_for_human_review == False
        promo.group_id = promoted.RECOMMENDED.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group() == promoted.NOT_PROMOTED
        assert unlisted_ver.needshumanreview_set.count() == 0
        assert listed_ver.needshumanreview_set.count() == 0

        # then with a group thats flag_for_human_review == True but pretend
        # the version has already been reviewed by a human (so it's not
        # necessary to flag it as needing human review again).
        listed_ver.update(human_review_date=self.days_ago(1))
        unlisted_ver.update(human_review_date=self.days_ago(1))
        listed_ver.file.update(is_signed=True)
        unlisted_ver.file.update(is_signed=True)
        promo.addon.reload()
        promo.group_id = promoted.NOTABLE.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []  # doesn't approve immediately
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group() == promoted.NOT_PROMOTED
        assert not listed_ver.reload().due_date
        assert not unlisted_ver.reload().due_date
        assert unlisted_ver.needshumanreview_set.count() == 0
        assert listed_ver.needshumanreview_set.count() == 0

        # then with a group thats flag_for_human_review == True without the
        # version having been reviewed by a human but not signed: also not
        # flagged.
        listed_ver.update(human_review_date=None)
        unlisted_ver.update(human_review_date=None)
        listed_ver.file.update(is_signed=False)
        unlisted_ver.file.update(is_signed=False)
        promo.addon.reload()
        promo.group_id = promoted.NOTABLE.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []  # doesn't approve immediately
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group() == promoted.NOT_PROMOTED
        assert not listed_ver.reload().due_date
        assert not unlisted_ver.reload().due_date
        assert unlisted_ver.needshumanreview_set.count() == 0
        assert listed_ver.needshumanreview_set.count() == 0

        # then with a group thats flag_for_human_review == True without the
        # version having been reviewed by a human but signed: this time we
        # should flag it.
        listed_ver.file.update(is_signed=True)
        unlisted_ver.file.update(is_signed=True)
        promo.addon.reload()
        promo.group_id = promoted.NOTABLE.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []  # doesn't approve immediately
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group() == promoted.NOT_PROMOTED
        self.assertCloseToNow(listed_ver.reload().due_date, now=get_review_due_date())
        self.assertCloseToNow(unlisted_ver.reload().due_date, now=get_review_due_date())
        assert unlisted_ver.needshumanreview_set.filter(is_active=True).count() == 1
        assert (
            unlisted_ver.needshumanreview_set.get().reason
            == unlisted_ver.needshumanreview_set.model.REASONS.ADDED_TO_PROMOTED_GROUP
        )
        assert listed_ver.needshumanreview_set.filter(is_active=True).count() == 1
        assert (
            listed_ver.needshumanreview_set.get().reason
            == unlisted_ver.needshumanreview_set.model.REASONS.ADDED_TO_PROMOTED_GROUP
        )

    def test_disabled_and_deleted_versions_flagged_for_human_review(self):
        addon = addon_factory(
            file_kw={'status': amo.STATUS_DISABLED, 'is_signed': True}
        )
        version = addon.find_latest_version(None, exclude=(), deleted=True)
        promo = PromotedAddon.objects.create(
            addon=addon, application_id=amo.FIREFOX.id, group_id=promoted.NOTABLE.id
        )
        assert promo.addon.promoted_group() == promoted.NOT_PROMOTED
        self.assertCloseToNow(version.reload().due_date, now=get_review_due_date())
        assert version.needshumanreview_set.filter(is_active=True).count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.ADDED_TO_PROMOTED_GROUP
        )

        # And if deleted too
        version.needshumanreview_set.update(is_active=False)
        version.update(due_date=None)
        version.delete()
        promo.save()
        self.assertCloseToNow(version.reload().due_date, now=get_review_due_date())
        assert version.needshumanreview_set.count() == 2
        needs_human_review = version.needshumanreview_set.latest('pk')
        assert (
            needs_human_review.reason
            == version.needshumanreview_set.model.REASONS.ADDED_TO_PROMOTED_GROUP
        )
        assert needs_human_review.is_active

        # even if the add-on is deleted
        version.needshumanreview_set.update(is_active=False)
        version.update(due_date=None)
        addon.delete()
        promo.save()
        self.assertCloseToNow(version.reload().due_date, now=get_review_due_date())
        assert version.needshumanreview_set.count() == 3
        needs_human_review = version.needshumanreview_set.latest('pk')
        assert (
            needs_human_review.reason
            == version.needshumanreview_set.model.REASONS.ADDED_TO_PROMOTED_GROUP
        )
        assert needs_human_review.is_active

    def test_approve_for_addon(self):
        core.set_user(user_factory())
        promo = PromotedAddon.objects.create(
            addon=addon_factory(
                version_kw={'version': '0.123a'},
                file_kw={'filename': 'webextension.xpi'},
            ),
            group_id=promoted.SPOTLIGHT.id,
        )
        # SPOTLIGHT doesnt have special signing states so won't be resigned
        # approve_for_addon is called automatically - SPOTLIGHT has immediate_approval
        promo.addon.reload()
        assert promo.addon.promoted_group() == promoted.SPOTLIGHT
        assert promo.addon.current_version.version == '0.123a'
