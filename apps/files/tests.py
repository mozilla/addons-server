from django import test

from files.models import File


class TestFile(test.TestCase):
    """
    Tests the methods of the File model.
    """

    fixtures = ['base/addons.json']

    def test_get_absolute_url(self):
        f = File.objects.get(id=11993)
        src = "crystalmethod"
        assert f.get_absolute_url(src).endswith(
                'downloads/file/11993/'
                'del.icio.us_bookmarks-1.0.43-fx.xpi?src=crystalmethod')
