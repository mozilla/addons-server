from nose.tools import eq_

from django.utils.encoding import force_unicode

import amo
import amo.tests
from addons.models import Addon
from editors.forms import get_review_form
from editors.helpers import NOMINATED_STATUSES
from editors.models import CannedResponse
from users.models import UserProfile


class TestReviewActions(amo.tests.TestCase):
    fixtures = ('base/users', 'base/addon_3615')

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.versions.all()[0]

        class FakeRequest:
            user = UserProfile.objects.get(pk=10482).user

        self.request = FakeRequest()
        self.file = self.version.files.all()[0]

    def set_status(self, status):
        self.addon.update(status=status)
        form = get_review_form({'addon_files': [self.file.pk]},
                                request=self.request,
                                addon=self.addon,
                                version=self.version)
        return form.helper.get_actions()

    def test_lite_nominated(self):
        status = self.set_status(amo.STATUS_LITE_AND_NOMINATED)
        eq_(force_unicode(status['prelim']['label']),
            'Retain preliminary review')

    def test_other_statuses(self):
        for status in amo.STATUS_CHOICES:
            if status in NOMINATED_STATUSES:
                return
            else:
                eq_(force_unicode(self.set_status(status)['prelim']['label']),
                    'Grant preliminary review')

    def test_reject(self):
        reject = self.set_status(amo.STATUS_UNREVIEWED)['reject']['details']
        assert force_unicode(reject).startswith('This will reject the add-on')

    def test_reject_lite(self):
        reject = self.set_status(amo.STATUS_LITE)['reject']['details']
        assert force_unicode(reject).startswith('This will reject the files')

    def test_not_public(self):
        # If the file is unreviewed then there is no option to reject,
        # so the length of the actions is one shorter
        eq_(len(self.set_status(amo.STATUS_UNREVIEWED)), 5)


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
        form = get_review_form({'addon_files': [self.file.pk]},
                               request=self.request, addon=self.addon,
                               version=self.version)
        choices = form.fields['canned_response'].choices[1][1]
        # choices is grouped by the sort_group, where choices[0] is the
        # default "Choose a response..." option.
        # Within that, it's paired by [group, [[response, name],...]].
        # So above, choices[1][1] gets the first real group's list of responses.
        eq_(len(choices), 1)
        assert self.cr_addon.response in choices[0]
        assert self.cr_app.response not in choices[0]
