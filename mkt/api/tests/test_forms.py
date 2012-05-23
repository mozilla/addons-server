import base64

from nose.tools import eq_

import amo
import amo.tests
from mkt.api.forms import PreviewJSONForm


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
