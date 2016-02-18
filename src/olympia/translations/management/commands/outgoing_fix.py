from django.core.management.base import BaseCommand

from olympia.translations.models import Translation


class Command(BaseCommand):
    help = """Fix http outgoing urls"""

    def handle(self, *args, **kw):
        total = Translation.objects.count()
        print 'Found %s translations' % total
        for k in range(0, total, 50):
            end = k + 50
            print 'Fixing translations: %s to %s' % (k, end)
            for obj in (Translation.objects.all().no_cache()
                        .order_by('autoid')[k:end].iterator()):
                if (obj.localized_string_clean and
                        'http://outgoing' in obj.localized_string_clean):
                    print 'Fixing translation:', obj.autoid
                    new = obj.localized_string_clean.replace(
                        'http://outgoing', 'https://outgoing')
                    obj.localized_string_clean = new
                    obj.save(update_fields=('localized_string_clean',))
