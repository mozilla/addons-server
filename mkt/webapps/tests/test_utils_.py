from nose.tools import eq_

import amo
import amo.tests

from addons.models import Preview
from mkt.webapps.utils import app_to_dict


class TestAppToDict(amo.tests.TestCase):
    # TODO: expand this and move more stuff out of
    # mkt/api/tests/test_handlers.

    def setUp(self):
        self.app = amo.tests.app_factory()

    def test_no_previews(self):
        eq_(app_to_dict(self.app)['previews'], [])

    def test_with_preview(self):
        obj = Preview.objects.create(**{'caption': 'foo',
            'filetype': 'image/png', 'thumbtype': 'image/png',
            'addon': self.app})
        preview = app_to_dict(self.app)['previews'][0]
        self.assertSetEqual(preview,
            ['caption', 'filetype', 'id', 'image_url', 'thumbnail_url',
             'resource_uri'])
        eq_(preview['caption'], 'foo')
        eq_(int(preview['id']), obj.pk)
