import mock

from django.utils.encoding import force_text

from olympia import amo
from olympia.amo.tests import (
    addon_factory, file_factory, TestCase, version_factory)
from olympia.addons.models import Addon
from olympia.editors.forms import ReviewForm
from olympia.editors.models import CannedResponse
from olympia.editors.utils import ReviewHelper
from olympia.users.models import UserProfile


class TestReviewForm(TestCase):
    fixtures = ('base/users', 'base/addon_3615')

    def setUp(self):
        super(TestReviewForm, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.versions.all()[0]

        class FakeRequest:
            user = UserProfile.objects.get(pk=10482)

        self.request = FakeRequest()
        self.file = self.version.files.all()[0]

    def get_form(self, data=None):
        return ReviewForm(
            data=data,
            helper=ReviewHelper(request=self.request, addon=self.addon,
                                version=self.version))

    def set_statuses(self, addon_status, file_status):
        self.file.update(status=file_status)
        self.addon.update(status=addon_status)
        # Need to clear self.version.all_files cache since we updated the file.
        del self.version.all_files
        form = self.get_form()
        return form.helper.get_actions(self.request)

    def test_actions_reject(self):
        reject = self.set_statuses(
            addon_status=amo.STATUS_NOMINATED,
            file_status=amo.STATUS_AWAITING_REVIEW)['reject']['details']
        assert force_text(reject).startswith('This will reject this version')

    def test_actions_addon_status_null(self):
        # If the add-on is null we only show info, comment and super review.
        assert len(self.set_statuses(addon_status=amo.STATUS_NULL,
                                     file_status=amo.STATUS_NULL)) == 3

    def test_actions_addon_status_deleted(self):
        # If the add-on is deleted we only show info, comment and super review.
        assert len(self.set_statuses(addon_status=amo.STATUS_DELETED,
                                     file_status=amo.STATUS_NULL)) == 3

    def test_actions_no_pending_files(self):
        # If the add-on has no pending files we only show info, comment and
        # super review.
        assert len(self.set_statuses(addon_status=amo.STATUS_PUBLIC,
                                     file_status=amo.STATUS_PUBLIC)) == 3
        assert len(self.set_statuses(addon_status=amo.STATUS_PUBLIC,
                                     file_status=amo.STATUS_BETA)) == 3
        assert len(self.set_statuses(addon_status=amo.STATUS_DISABLED,
                                     file_status=amo.STATUS_DISABLED)) == 3

    @mock.patch('olympia.access.acl.action_allowed')
    def test_actions_admin_flagged_addon_actions(self, action_allowed_mock):
        self.addon.update(admin_review=True)
        # Test with an admin editor.
        action_allowed_mock.return_value = True
        status = self.set_statuses(addon_status=amo.STATUS_NOMINATED,
                                   file_status=amo.STATUS_AWAITING_REVIEW)
        assert 'public' in status.keys()
        # Test with an non-admin editor.
        action_allowed_mock.return_value = False
        status = self.set_statuses(addon_status=amo.STATUS_NOMINATED,
                                   file_status=amo.STATUS_AWAITING_REVIEW)
        assert 'public' not in status.keys()

    def test_canned_responses_no_app(self):
        self.cr_addon = CannedResponse.objects.create(
            name=u'addon reason', response=u'addon reason body',
            sort_group=u'public', type=amo.CANNED_RESPONSE_ADDON)
        self.set_statuses(addon_status=amo.STATUS_NOMINATED,
                          file_status=amo.STATUS_AWAITING_REVIEW)
        form = self.get_form()
        choices = form.fields['canned_response'].choices[1][1]
        # choices is grouped by the sort_group, where choices[0] is the
        # default "Choose a response..." option.
        # Within that, it's paired by [group, [[response, name],...]].
        # So above, choices[1][1] gets the first real group's list of
        # responses.
        assert len(choices) == 1
        assert self.cr_addon.response in choices[0]

    def test_comments_and_action_required_by_default(self):
        form = self.get_form()
        assert not form.is_bound
        form = self.get_form(data={})
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {
            'action': [u'This field is required.'],
            'comments': [u'This field is required.']
        }

        # Alter the action to make it not require comments to be sent
        # regardless of what the action actually is, what we want to test is
        # the form behaviour.
        form = self.get_form(data={'action': 'reply'})
        form.helper.actions['reply']['comments'] = False
        assert form.is_bound
        assert form.is_valid()
        assert not form.errors

    def test_versions_queryset(self):
        addon_factory()
        file_factory(version=self.addon.current_version)
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        form = self.get_form()
        assert not form.is_bound
        assert form.fields['versions'].required is False
        assert list(form.fields['versions'].queryset) == []

        # With post-review permission, the reject_multiple_versions action will
        # be available, resetting the queryset of allowed choices.
        self.grant_permission(self.request.user, 'Addons:PostReview')
        form = self.get_form()
        assert not form.is_bound
        assert form.fields['versions'].required is False
        assert list(form.fields['versions'].queryset) == [
            self.addon.current_version]

    def test_versions_required(self):
        self.grant_permission(self.request.user, 'Addons:PostReview')
        form = self.get_form(data={
            'action': 'reject_multiple_versions', 'comments': 'lol'})
        form.helper.actions['reject_multiple_versions']['versions'] = True
        assert form.is_bound
        assert not form.is_valid()
        assert form.errors == {
            'versions': [u'This field is required.']
        }
