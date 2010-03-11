from nose.tools import eq_
import test_utils

from tags.models import Tag


class TestTagManager(test_utils.TestCase):

    def test_not_blacklisted(self):
        """Make sure Tag Manager filters right for not blacklisted tags."""
        tag1 = Tag(tag_text='abc', blacklisted=False)
        tag1.save()
        tag2 = Tag(tag_text='swearword', blacklisted=True)
        tag2.save()

        eq_(Tag.objects.all().count(), 2)
        eq_(Tag.objects.not_blacklisted().count(), 1)
        eq_(Tag.objects.not_blacklisted()[0], tag1)
