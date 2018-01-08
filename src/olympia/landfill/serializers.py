import random

from rest_framework import serializers

from olympia import amo
from olympia.addons.forms import icons
from olympia.addons.models import AddonUser, Preview
from olympia.addons.utils import generate_addon_guid
from olympia.amo.tests import addon_factory, user_factory, version_factory
from olympia.constants.applications import APPS, FIREFOX
from olympia.constants.base import (
    ADDON_EXTENSION, ADDON_PERSONA, STATUS_PUBLIC)
from olympia.landfill.collection import generate_collection
from olympia.landfill.generators import generate_themes
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile


class GenerateAddonsSerializer(serializers.Serializer):
    count = serializers.IntegerField(default=10)

    def create_generic_featured_addons(self):
        """Creates 10 addons.

        Creates exactly 10 random addons with users that are also randomly
        generated.

        """
        for _ in range(10):
            AddonUser.objects.create(
                user=user_factory(), addon=addon_factory())

    def create_featured_addon_with_version(self):
        """Creates a custom addon named 'Ui-Addon'.

        This addon will be a featured addon and will have a featured collecton
        attatched to it. It will belong to the user uitest.

        It has 1 preview, 5 reviews, and 2 authors. The second author is named
        'ui-tester2'. It has a version number as well as a beta version.

        """
        default_icons = [x[0] for x in icons() if x[0].startswith('icon/')]
        addon = addon_factory(
            status=STATUS_PUBLIC,
            type=ADDON_EXTENSION,
            average_daily_users=5000,
            users=[UserProfile.objects.get(username='uitest')],
            average_rating=5,
            description=u'My Addon description',
            file_kw={
                'hash': 'fakehash',
                'platform': amo.PLATFORM_ALL.id,
                'size': 42,
            },
            guid=generate_addon_guid(),
            icon_type=random.choice(default_icons),
            name=u'Ui-Addon',
            public_stats=True,
            slug='ui-test-2',
            summary=u'My Addon summary',
            tags=['some_tag', 'another_tag', 'ui-testing',
                  'selenium', 'python'],
            total_ratings=500,
            weekly_downloads=9999999,
            developer_comments='This is a testing addon.',
        )
        Preview.objects.create(addon=addon, position=1)
        Rating.objects.create(addon=addon, rating=5, user=user_factory())
        Rating.objects.create(addon=addon, rating=5, user=user_factory())
        Rating.objects.create(addon=addon, rating=5, user=user_factory())
        Rating.objects.create(addon=addon, rating=5, user=user_factory())
        Rating.objects.create(addon=addon, rating=5, user=user_factory())
        Rating.objects.create(addon=addon, rating=5, user=user_factory())
        Rating.objects.create(addon=addon, rating=5, user=user_factory())
        Rating.objects.create(addon=addon, rating=5, user=user_factory())
        AddonUser.objects.create(user=user_factory(username='ui-tester2'),
                                 addon=addon, listed=True)
        version_factory(addon=addon, file_kw={'status': amo.STATUS_BETA},
                        version='1.1beta')
        addon.save()
        generate_collection(addon, app=FIREFOX)
        print(
            'Created addon {0} for testing successfully'
            .format(addon.name))

    def create_featured_theme(self):
        """Creates a custom theme named 'Ui-Test Theme'.

        This theme will be a featured theme and will belong to the uitest user.

        It has one author.

        """
        addon = addon_factory(
            status=STATUS_PUBLIC,
            type=ADDON_PERSONA,
            average_daily_users=4242,
            users=[UserProfile.objects.get(username='uitest')],
            average_rating=5,
            description=u'My UI Theme description',
            file_kw={
                'hash': 'fakehash',
                'platform': amo.PLATFORM_ALL.id,
                'size': 42,
            },
            guid=generate_addon_guid(),
            homepage=u'https://www.example.org/',
            name=u'Ui-Test Theme',
            public_stats=True,
            slug='ui-test',
            summary=u'My UI theme summary',
            support_email=u'support@example.org',
            support_url=u'https://support.example.org/support/ui-theme-addon/',
            tags=['some_tag', 'another_tag', 'ui-testing',
                    'selenium', 'python'],
            total_ratings=777,
            weekly_downloads=123456,
            developer_comments='This is a testing theme, used within pytest.',
        )
        addon.save()
        generate_collection(
            addon,
            app=FIREFOX,
            type=amo.COLLECTION_FEATURED)
        print('Created Theme {0} for testing successfully'.format(addon.name))

    def create_featured_collections(self):
        """Creates exactly 4 collections that are featured.

        This fixture uses the generate_collection function from olympia.

        """
        for _ in range(4):
            addon = addon_factory(type=amo.ADDON_EXTENSION)
            generate_collection(
                addon, APPS['firefox'], type=amo.COLLECTION_FEATURED)

    def create_featured_themes(self):
        """Creates exactly 6 themes that will be not featured.

        These belong to the user uitest.

        It will also create 6 themes that are featured with random authors.

        """
        generate_themes(6, 'uitest@mozilla.com')
        for _ in range(6):
            addon = addon_factory(status=STATUS_PUBLIC, type=ADDON_PERSONA)
            generate_collection(addon, app=FIREFOX)
