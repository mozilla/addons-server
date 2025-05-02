from django.conf import settings
from django.core.management import call_command

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.promoted.models import (
    PromotedAddonPromotion,
    PromotedAddonVersion,
    PromotedGroup,
)


class TestPromoteByFirefoxThemesCommand(TestCase):
    def test_basic(self):
        other_user = user_factory()
        firefox_user = user_factory(pk=settings.TASK_USER_ID)
        non_affected = [
            # Not By Firefox user.
            addon_factory(type=amo.ADDON_STATICTHEME, users=[other_user]),
            # Not a theme.
            addon_factory(type=amo.ADDON_EXTENSION, users=[firefox_user]),
            # Not public.
            addon_factory(
                type=amo.ADDON_STATICTHEME,
                status=amo.STATUS_DISABLED,
                users=[firefox_user],
            ),
        ]
        # Already promoted, should not cause an error.
        already_promoted = addon_factory(
            type=amo.ADDON_STATICTHEME,
            users=[firefox_user],
            promoted_id=PROMOTED_GROUP_CHOICES.LINE,
        )

        expected_affected = addon_factory(
            type=amo.ADDON_STATICTHEME, users=[firefox_user]
        )

        call_command('promote_by_firefox_themes')

        for addon in non_affected:
            assert not PromotedAddonPromotion.objects.filter(addon=addon).exists()
            assert not PromotedAddonVersion.objects.filter(
                version__addon=addon
            ).exists()

        for addon in (already_promoted, expected_affected):
            assert (
                addon.current_version.promoted_versions.all()
                .filter(application_id=amo.FIREFOX.id)
                .exists()
            )

            assert list(addon.promoted_groups()) == [
                PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
            ]
