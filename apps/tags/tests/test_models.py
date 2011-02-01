from nose.tools import eq_
import test_utils

from addons.models import Addon
from tags.models import AddonTag, Tag
from tags.tasks import clean_tag


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


class TestManagement(test_utils.TestCase):
    fixtures = ['base/addon_3615',
                'base/addon_5369',
                'tags/tags.json',
                'base/user_4043307',
                'base/user_2519']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.another = Addon.objects.get(pk=5369)

    def test_clean_tags(self):
        start = Tag.objects.count()
        caps = Tag.objects.create(tag_text='Sun')
        space = Tag.objects.create(tag_text='  Sun')

        clean_tag(caps.pk)
        clean_tag(space.pk)
        eq_(Tag.objects.count(), start)
        # Just to check another run doesn't make more changes.
        clean_tag(space.pk)
        eq_(Tag.objects.count(), start)

    def test_clean_addons_tags(self):
        space = Tag.objects.create(tag_text='  Sun')
        start = self.addon.tags.count()

        AddonTag.objects.create(tag=space, addon=self.addon)
        AddonTag.objects.create(tag=space, addon=self.another)

        eq_(self.another.tags.count(), 1)
        eq_(self.addon.tags.count(), start + 1)

        for tag in Tag.objects.all():
            clean_tag(tag.pk)

        # There is '  Sun' and 'sun' on addon, one gets deleted.
        eq_(self.addon.tags.count(), start)
        # There is 'sun' on another, should not be deleted.
        eq_(self.another.tags.count(), 1)

    def test_clean_doesnt_delete(self):
        space = Tag.objects.create(tag_text=' Sun')
        start = self.addon.tags.count()

        AddonTag.objects.create(tag=space, addon=self.another)

        eq_(self.another.tags.count(), 1)
        for tag in Tag.objects.all():
            clean_tag(tag.pk)

        # The 'sun' doesn't get deleted.
        eq_(self.addon.tags.count(), start)
        # There is 'sun' on another, should not be deleted.
        eq_(self.another.tags.count(), 1)

    def test_clean_multiple(self):
        for tag in ['sun', 'beach', 'sky']:
            caps = tag.upper()
            space = '  %s' % tag
            other = '. %s!  ' % tag
            for garbage in [caps, space, other]:
                garbage = Tag.objects.create(tag_text=garbage)
                for addon in (self.addon, self.another):
                    AddonTag.objects.create(tag=garbage, addon=addon)

        for tag in Tag.objects.all():
            clean_tag(tag.pk)

        eq_(self.addon.tags.count(), 5)
        eq_(self.another.tags.count(), 3)

    def setup_blacklisted(self):
        self.new = Tag.objects.create(tag_text=' Sun', blacklisted=True)
        self.old = Tag.objects.get(tag_text='sun')

    def test_blacklisted(self):
        self.setup_blacklisted()
        clean_tag(self.old.pk)
        assert not Tag.objects.get(tag_text='sun').blacklisted
        clean_tag(self.new.pk)
        assert Tag.objects.get(tag_text='sun').blacklisted

    def test_blacklisted_inverted(self):
        self.setup_blacklisted()
        clean_tag(self.new.pk)
        assert Tag.objects.get(tag_text='sun').blacklisted
        clean_tag(self.old.pk)
        assert Tag.objects.get(tag_text='sun').blacklisted
