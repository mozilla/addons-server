from nose.tools import eq_
import test_utils

from bandwagon.models import Collection


class TestCollections(test_utils.TestCase):
    fixtures = ['bandwagon/test_models']

    def test_translation_default(self):
        """Make sure we're getting strings from the default locale."""
        c = Collection.objects.get(pk=512)
        eq_(unicode(c.name), 'yay')
