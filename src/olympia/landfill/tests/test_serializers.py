from olympia import amo
from olympia.access.models import Group
from olympia.amo.tests import TestCase
from olympia.applications.models import AppVersion
from olympia.landfill.serializers import GenerateAddonsSerializer


class TestGenerateAddonsSerializer(TestCase):
    def test_create_installable_addon(self):
        Group.objects.create(name='Admins', rules='*:*')
        AppVersion.objects.create(
            application=amo.FIREFOX.id, version=amo.DEFAULT_WEBEXT_MIN_VERSION
        )
        AppVersion.objects.create(application=amo.FIREFOX.id, version='*')
        AppVersion.objects.create(
            application=amo.ANDROID.id, version=amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID
        )
        AppVersion.objects.create(application=amo.ANDROID.id, version='*')
        serializer = GenerateAddonsSerializer()

        # This should not raise.
        serializer.create_installable_addon()
