import base64

from nose.tools import eq_

from addons.models import Addon
import amo
import amo.tests
from mkt.api.forms import PreviewJSONForm, StatusForm


class TestPreviewForm(amo.tests.TestCase, amo.tests.AMOPaths):

    def setUp(self):
        self.file = base64.b64encode(open(self.mozball_image(), 'r').read())

    def test_bad_type(self):
        form = PreviewJSONForm({'file': {'data': self.file, 'type': 'wtf?'},
                                'position': 1})
        assert not form.is_valid()
        eq_(form.errors['file'], ['Images must be either PNG or JPG.'])

    def test_bad_file(self):
        file_ = base64.b64encode(open(self.xpi_path('langpack'), 'r').read())
        form = PreviewJSONForm({'file': {'data': file_, 'type': 'image/png'},
                                'position': 1})
        assert not form.is_valid()
        eq_(form.errors['file'], ['Images must be either PNG or JPG.'])

    def test_position_missing(self):
        form = PreviewJSONForm({'file': {'data': self.file,
                                         'type': 'image/jpg'}})
        assert not form.is_valid()
        eq_(form.errors['position'], ['This field is required.'])

    def test_preview(self):
        form = PreviewJSONForm({'file': {'type': '', 'data': ''},
                                'position': 1})
        assert not form.is_valid()
        eq_(form.errors['file'], ['Images must be either PNG or JPG.'])

    def test_not_json(self):
        form = PreviewJSONForm({'file': 1, 'position': 1})
        assert not form.is_valid()
        eq_(form.errors['file'], ['File must be a dictionary.'])

    def test_not_file(self):
        form = PreviewJSONForm({'position': 1})
        assert not form.is_valid()
        eq_(form.errors['file'], ['This field is required.'])


class TestSubmitForm(amo.tests.TestCase):

    def setUp(self):
        self.addon = Addon()

    def test_status_null(self):
        self.addon.status = amo.STATUS_NULL
        status = StatusForm(instance=self.addon).fields['status']
        eq_([k for k, v in status.choices],
            ['incomplete', 'pending'])

    def test_status_public(self):
        self.addon.status = amo.STATUS_PUBLIC_WAITING
        status = StatusForm(instance=self.addon).fields['status']
        eq_([k for k, v in status.choices],
            ['public', 'waiting'])

    def test_status_other(self):
        for s in amo.STATUS_CHOICES.keys():
            if s in [amo.STATUS_NULL, amo.STATUS_PUBLIC_WAITING]:
                continue
            self.addon.status = s
            status = StatusForm(instance=self.addon).fields['status']
            eq_([k for k, v in status.choices], [k])
