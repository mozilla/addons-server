from datetime import datetime, timedelta

from nose.tools import eq_
import test_utils

from addons.models import Addon
from tags.models import AddonTag, Tag
from tags.management.commands import limit_tags
from tags.tests.test_helpers import create_tags
from users.models import UserProfile


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
                'tags/tags.json',
                'base/user_4043307',
                'base/user_2519']

    def test_limit_tags(self):
        addon = Addon.objects.get(pk=3615)
        user = UserProfile.objects.get(pk=4043307)
        current = list(addon.addon_tags.all())
        not_blacklisted = list(addon.addon_tags.filter(tag__blacklisted=False))

        # This addon has under 20 tags, so no change.
        limit_tags.handle_addon(addon)
        assert addon.addon_tags.count() == len(current)

        create_tags(addon, user, limit_tags.MAX_TAGS + 8)

        # Check that there's at least one blacklisted AddonTag.
        tags = addon.addon_tags.values_list('tag__blacklisted', flat=True)
        eq_(len(set(tags)), 2)

        eq_(addon.addon_tags.count(), len(current) + limit_tags.MAX_TAGS + 8)
        limit_tags.handle_addon(addon)
        eq_(addon.addon_tags.count(), limit_tags.MAX_TAGS)

        # Check that the early blacklisted AddonTag got removed.
        tags = addon.addon_tags.values_list('tag__blacklisted', flat=True)
        eq_(len(set(tags)), 1)

        # Check all the old tags are in there.
        for k in not_blacklisted:
            assert k in addon.addon_tags.all()

    def test_developer_tags_priority(self):
        addon = Addon.objects.get(pk=3615)
        author = addon.authors.all()[0]
        user_a = UserProfile.objects.get(pk=4043307)
        user_b = UserProfile.objects.get(pk=2519)

        # Move back user_b's created date so their tags
        # will get priority
        user_b.created = user_a.created - timedelta(days=2)
        user_b.save()

        create_tags(addon, user_a, (limit_tags.MAX_TAGS / 2) + 8)
        create_tags(addon, user_b, (limit_tags.MAX_TAGS / 2) + 8)

        limit_tags.handle_addon(addon)
        eq_(addon.addon_tags.count(), limit_tags.MAX_TAGS)

        # Check that all the tags are the developers, or user_b
        # and user_a tags are removed
        for tag in addon.addon_tags.all():
            assert tag.user in [author, user_b]
