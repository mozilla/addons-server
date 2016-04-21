import mock

from django.utils.encoding import force_unicode

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.addons.models import Addon
from olympia.editors.forms import ReviewForm
from olympia.editors.helpers import NOMINATED_STATUSES, ReviewHelper
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

    def set_status(self, status):
        self.addon.update(status=status)
        form = ReviewForm(
            {'addon_files': [self.file.pk]},
            helper=ReviewHelper(request=self.request, addon=self.addon,
                                version=self.version))
        return form.helper.get_actions(self.request, self.addon)

    def test_lite_nominated(self):
        status = self.set_status(amo.STATUS_LITE_AND_NOMINATED)
        assert force_unicode(status['prelim']['label']) == (
            'Retain preliminary review')

    def test_other_statuses(self):
        for status in Addon.STATUS_CHOICES:
            statuses = NOMINATED_STATUSES + (
                amo.STATUS_NULL, amo.STATUS_DELETED)
            if status in statuses:
                return
            else:
                label = self.set_status(status)['prelim']['label']
                assert force_unicode(label) == 'Grant preliminary review'

    def test_nominated_unlisted_addon_no_prelim(self):
        self.addon.update(is_listed=False)
        actions = self.set_status(amo.STATUS_NOMINATED)
        assert 'prelim' not in actions
        assert actions['public']['label'] == 'Grant full review'

    def test_reject(self):
        reject = self.set_status(amo.STATUS_UNREVIEWED)['reject']['details']
        assert force_unicode(reject).startswith('This will reject the add-on')

    def test_reject_lite(self):
        reject = self.set_status(amo.STATUS_LITE)['reject']['details']
        assert force_unicode(reject).startswith('This will reject the files')

    def test_not_public(self):
        # If the file is unreviewed then there is no option to reject,
        # so the length of the actions is one shorter
        assert len(self.set_status(amo.STATUS_UNREVIEWED)) == 5

    def test_addon_status_null(self):
        # If the add-on is null we only show info, comment and super review.
        assert len(self.set_status(amo.STATUS_NULL)) == 3

    def test_addon_status_deleted(self):
        # If the add-on is deleted we only show info, comment and super review.
        assert len(self.set_status(amo.STATUS_DELETED)) == 3

    @mock.patch('olympia.access.acl.action_allowed')
    def test_admin_flagged_addon_actions(self, action_allowed_mock):
        self.addon.update(admin_review=True)
        # Test with an admin editor.
        action_allowed_mock.return_value = True
        status = self.set_status(amo.STATUS_LITE_AND_NOMINATED)
        assert 'public' in status.keys()
        assert 'prelim' in status.keys()
        # Test with an non-admin editor.
        action_allowed_mock.return_value = False
        status = self.set_status(amo.STATUS_LITE_AND_NOMINATED)
        assert 'public' not in status.keys()
        assert 'prelim' not in status.keys()


class TestCannedResponses(TestReviewActions):
    fixtures = ('base/users', 'base/addon_3615')

    def setUp(self):
        super(TestCannedResponses, self).setUp()
        self.cr_addon = CannedResponse.objects.create(
            name=u'addon reason', response=u'addon reason body',
            sort_group=u'public', type=amo.CANNED_RESPONSE_ADDON)
        self.cr_app = CannedResponse.objects.create(
            name=u'app reason', response=u'app reason body',
            sort_group=u'public', type=amo.CANNED_RESPONSE_APP)

    def test_no_app(self):
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
        assert self.cr_app.response not in choices[0]
