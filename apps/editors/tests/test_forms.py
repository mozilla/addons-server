from nose.tools import eq_
import test_utils

from django.utils.encoding import force_unicode

from addons.models import Addon
import amo
from editors.forms import get_review_form
from editors.helpers import NOMINATED_STATUSES
from files.models import File
from users.models import UserProfile

from pyquery import PyQuery as pq


class TestReviewActions(test_utils.TestCase):
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
        eq_(len(self.set_status(amo.STATUS_UNREVIEWED)), 4)
