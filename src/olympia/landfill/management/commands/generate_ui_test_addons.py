from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.utils import translation

from olympia.landfill.serializers import GenerateAddonsSerializer


class Command(BaseCommand):
    """
    Generate addons used specifically for the Integration Tests.

    This will generate 10 addons with the name Ui-Addon, 1 Addon named
    Ui-Addon-Test, 1 Featured theme, 4 featured collections, and 6 themes that
    will not be marked as featured.

    Usage:

        python manage.py generate_ui_test_addons

    """

    def handle(self, *args, **kwargs):
        translation.activate('en-US')
        serializer = GenerateAddonsSerializer()
        serializer.create_generic_featured_addons()
        serializer.create_featured_addon_with_version()
        serializer.create_featured_theme()
        serializer.create_featured_collections()
        serializer.create_featured_themes()
        cache.clear()
        call_command('clear_cache')
