import test_utils

from addons.models import Addon


class TestCase(test_utils.TestCase):
    """TestCase subclass that automatically updates `current_version` for each
    addon."""

    def setUp(self):
        super(TestCase, self).setUp()
        for addon in Addon.objects.all():
            addon.update_current_version()
