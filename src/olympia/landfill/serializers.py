# -*- coding: utf-8 -*-

import mimetypes
import random

from django.conf import settings
from django.utils.translation import activate
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import RequestFactory
from rest_framework import serializers

from olympia.amo.tests import user_factory, addon_factory, copy_file_to_temp
from olympia import amo
from olympia.addons.forms import icons
from olympia.addons.models import AddonUser, Preview, Addon
from olympia.addons.utils import generate_addon_guid
from olympia.constants.applications import APPS, FIREFOX
from olympia.constants.base import (
    ADDON_EXTENSION,
    ADDON_PERSONA,
    STATUS_PUBLIC
)
from olympia.landfill.collection import generate_collection
from olympia.landfill.generators import generate_themes
from olympia.landfill.user import generate_user
from olympia.files.tests.test_file_viewer import get_file
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile
from olympia.devhub.tasks import create_version_for_upload


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

    def create_named_addon_with_author(self, name, author=None):
        """Create a generic addon and a user.

        The user will be created if a user is not given.

        """

        if author is None:
            author = user_factory()
        try:
            generate_user(author)
        except Exception:  # django.db.utils.IntegrityError
            # If the user is already made, use that same user,
            # if not use created user
            addon = addon_factory(
                status=STATUS_PUBLIC,
                users=[UserProfile.objects.get(username=author)],
                name=u'{}'.format(name),
                slug=u'{}'.format(name),
            )
            addon.save()
        else:
            addon = addon_factory(
                status=STATUS_PUBLIC,
                users=[UserProfile.objects.get(username=author.username)],
                name=u'{}'.format(name),
                slug=u'{}'.format(name),
            )
            addon.save()
        return addon

    def create_featured_addon_with_version(self):
        """Creates a custom addon named 'Ui-Addon'.

        This addon will be a featured addon and will have a featured collecton
        attatched to it. It will belong to the user uitest.

        It has 1 preview, 5 reviews, and 2 authors. The second author is named
        'ui-tester2'. It has a version number.

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
        addon.save()
        generate_collection(addon, app=FIREFOX)
        print(
            'Created addon {0} for testing successfully'
            .format(addon.name))

    def create_featured_addon_with_version_for_install(self):
        """Creates a custom addon named 'Ui-Addon'.

        This addon will be a featured addon and will have a featured collecton
        attatched to it. It will belong to the user uitest.

        It has 1 preview, 5 reviews, and 2 authors. The second author is named
        'ui-tester2'. It has a version number.

        """
        default_icons = [x[0] for x in icons() if x[0].startswith('icon/')]
        try:
            addon = Addon.objects.get(guid='@webextension-guid')
        except Addon.DoesNotExist:
            addon = addon_factory(
                status=STATUS_PUBLIC,
                type=ADDON_EXTENSION,
                file_kw=False,
                average_daily_users=5000,
                users=[UserProfile.objects.get(username='uitest')],
                average_rating=5,
                description=u'My Addon description',
                guid='@webextension-guid',
                icon_type=random.choice(default_icons),
                name=u'Ui-Addon-Install',
                public_stats=True,
                slug='ui-test-install',
                summary=u'My Addon summary',
                tags=['some_tag', 'another_tag', 'ui-testing',
                      'selenium', 'python'],
                weekly_downloads=9999999,
                developer_comments='This is a testing addon.',
            )
            addon.save()
            generate_collection(addon, app=FIREFOX)
            print(
                'Created addon {0} for testing successfully'
                .format(addon.name))
        return addon

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

    def create_a_named_collection_and_addon(self, name, author):
        """Creates a collection with a name and author."""

        generate_collection(
            self.create_named_addon_with_author(name, author=author),
            app=FIREFOX,
            author=UserProfile.objects.get(username=author),
            type=amo.COLLECTION_FEATURED,
            name=name
        )

    def create_installable_addon(self):
        activate('en-US')

        # using whatever add-on you already have should work imho, otherwise
        # fall back to a new one for test purposes
        addon = self.create_featured_addon_with_version_for_install()

        # the user the add-on gets created with
        user = UserProfile.objects.get(username='uitest')

        user, _ = UserProfile.objects.get_or_create(
            pk=settings.TASK_USER_ID,
            defaults={'email': 'admin@mozilla.com', 'username': 'admin'})

        # generate a proper uploaded file that simulates what django requires
        # as request.POST
        file_to_upload = 'webextension_signed_already.xpi'
        file_path = get_file(file_to_upload)

        # make sure we are not using the file in the source-tree but a
        # temporary one to avoid the files get moved somewhere else and
        # deleted from source tree
        with copy_file_to_temp(file_path) as temporary_path:
            data = open(temporary_path).read()
            filedata = SimpleUploadedFile(
                file_to_upload,
                data,
                content_type=mimetypes.guess_type(file_to_upload)[0])

            # now, lets upload the file into the system
            from olympia.devhub.views import handle_upload

            request = RequestFactory().get('/')
            request.user = user

            upload = handle_upload(
                filedata=filedata,
                request=request,
                channel=amo.RELEASE_CHANNEL_LISTED,
                addon=addon,
            )

            # And let's create a new version for that upload.
            create_version_for_upload(
                upload.addon, upload, amo.RELEASE_CHANNEL_LISTED)

            # Change status to public
            addon.update(status=amo.STATUS_PUBLIC)
