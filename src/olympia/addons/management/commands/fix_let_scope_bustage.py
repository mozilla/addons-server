from django.core.management.base import BaseCommand, CommandError

from olympia.amo.utils import chunked
from olympia.files.tasks import fix_let_scope_bustage_in_addons


class Command(BaseCommand):
    args = '<addon_id addon_id ...>'
    help = """Fix the "let scope bustage" (bug 1224686) for a list of add-ons.
Only the last version of each add-on will be fixed, and its version bumped."""

    def handle(self, *args, **options):
        if len(args) == 0:
            raise CommandError('Please provide at least one add-on id to fix.')

        addon_ids = [int(addon_id) for addon_id in args]
        for chunk in chunked(addon_ids, 100):
            fix_let_scope_bustage_in_addons.delay(chunk)
