from olympia.amo.tests import TestCase

from olympia.core.tests.db_tests_testapp.models import TestRegularCharField


class TestUtf8mb4Support(TestCase):
    """Utf8mb4 encoding related tests."""

    def test_max_length(self):
        TestRegularCharField.objects.create(name='a' * 255)

        assert TestRegularCharField.objects.get().name == 'a' * 255

        TestRegularCharField.objects.all().delete()

        # This still works, mysql reserves 4 bytes per character
        # which this perfectly matches
        TestRegularCharField.objects.create(name=u'🔍' * 255)

        assert TestRegularCharField.objects.get().name == u'🔍' * 255

        # Now, the red heart emoji is 6 bytes long though...
        TestRegularCharField.objects.create(name=u'❤️' * 255)

        assert TestRegularCharField.objects.get().name == u'❤️' * 255
