import mock

from django.utils.encoding import force_text

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.addons.models import Addon
from olympia.editors.forms import ReviewForm
from olympia.editors.helpers import ReviewHelper
from olympia.editors.models import CannedResponse
from olympia.users.models import UserProfile


class TestReviewActions(TestCase):
    fixtures = ('base/users', 'base/addon_3615')

    def setUp(self):
        super(TestReviewActions, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.versions.all()[0]

        class FakeRequest:
            user = UserProfile.objects.get(pk=10482)

        self.request = FakeRequest()
        self.file = self.version.files.all()[0]

    def set_statuses(self, addon_status, file_status):
        self.file.update(status=file_status)
        self.addon.update(status=addon_status)
        # Need to clear self.version.all_files cache since we updated the file.
        del self.version.all_files
        form = ReviewForm(
            {'addon_files': [self.file.pk]},
            helper=ReviewHelper(request=self.request, addon=self.addon,
                                version=self.version))
        return form.helper.get_actions(self.request, self.addon)

    def test_reject(self):
        reject = self.set_statuses(
            addon_status=amo.STATUS_NOMINATED,
            file_status=amo.STATUS_AWAITING_REVIEW)['reject']['details']
        assert force_text(reject).startswith('This will reject this version')

    def test_addon_status_null(self):
        # If the add-on is null we only show info, comment and super review.
        assert len(self.set_statuses(addon_status=amo.STATUS_NULL,
                                     file_status=amo.STATUS_NULL)) == 3

    def test_addon_status_deleted(self):
        # If the add-on is deleted we only show info, comment and super review.
        assert len(self.set_statuses(addon_status=amo.STATUS_DELETED,
                                     file_status=amo.STATUS_NULL)) == 3

    def test_no_pending_files(self):
        # If the add-on has no pending files we only show info, comment and
        # super review.
        assert len(self.set_statuses(addon_status=amo.STATUS_PUBLIC,
                                     file_status=amo.STATUS_PUBLIC)) == 3
        assert len(self.set_statuses(addon_status=amo.STATUS_PUBLIC,
                                     file_status=amo.STATUS_BETA)) == 3
        assert len(self.set_statuses(addon_status=amo.STATUS_DISABLED,
                                     file_status=amo.STATUS_DISABLED)) == 3

    @mock.patch('olympia.access.acl.action_allowed')
    def test_admin_flagged_addon_actions(self, action_allowed_mock):
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


class TestCannedResponses(TestReviewActions):
    fixtures = ('base/users', 'base/addon_3615')

    def setUp(self):
        super(TestCannedResponses, self).setUp()
        self.cr_addon = CannedResponse.objects.create(
            name=u'addon reason', response=u'addon reason body',
            sort_group=u'public', type=amo.CANNED_RESPONSE_ADDON)

    def test_no_app(self):
        self.set_statuses(addon_status=amo.STATUS_NOMINATED,
                          file_status=amo.STATUS_AWAITING_REVIEW)
        form = ReviewForm(
            {'addon_files': [self.file.pk]},
            helper=ReviewHelper(request=self.request, addon=self.addon,
                                version=self.version))
        choices = form.fields['canned_response'].choices[1][1]
        # choices is grouped by the sort_group, where choices[0] is the
        # default "Choose a response..." option.
        # Within that, it's paired by [group, [[response, name],...]].
        # So above, choices[1][1] gets the first real group's list of
        # responses.
        assert len(choices) == 1
        assert self.cr_addon.response in choices[0]
