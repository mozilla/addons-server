from django.core.management.base import BaseCommand

from tags.models import Tag
from tags.tasks import clean_tag


class Command(BaseCommand):
    # https://bugzilla.mozilla.org/show_bug.cgi?id=612811
    help = 'Migration to clean up old tags per 612811'

    def handle(self, *args, **kw):
        pks = list(Tag.objects.values_list('pk', flat=True).order_by('pk'))

        print "Found: %s tags to clean and adding to celery." % len(pks)
        for pk in pks:
            clean_tag.delay(pk)
