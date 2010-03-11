from nose.tools import eq_
import test_utils

from bandwagon.models import Collection


class TestCollections(test_utils.TestCase):
    fixtures = ['bandwagon/test_models']

    def test_translation_default(self):
        """Make sure we're getting strings from the default locale."""
        c = Collection.objects.get(pk=512)
        eq_(unicode(c.name), 'yay')

    def test_listed(self):
        """Make sure the manager's listed() filter works."""
        # make a private collection
        private = Collection(
            name="Hello", uuid="4e2a1acc-39ae-47ec-956f-46e080ac7f69",
            listed=False)
        private.save()

        c = Collection.objects.get(pk=512)

        listed = Collection.objects.listed()

        eq_(listed.count(), 1)
        eq_(listed[0], c)
