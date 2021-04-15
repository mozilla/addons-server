from olympia import amo
from olympia.access.models import Group
from olympia.amo.tests import TestCase
from olympia.applications.models import AppVersion
from olympia.landfill.serializers import GenerateAddonsSerializer


class TestGenerateAddonsSerializer(TestCase):
    def test_create_installable_addon(self):
        Group.objects.get_or_create(pk=1, defaults={'name': 'Admins', 'rules': '*:*'})
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.0')
        AppVersion.objects.create(application=amo.FIREFOX.id, version='*')
        AppVersion.objects.create(application=amo.ANDROID.id, version='48.0')
        AppVersion.objects.create(application=amo.ANDROID.id, version='*')
        serializer = GenerateAddonsSerializer()

        # This should not raise.
        serializer.create_installable_addon()
