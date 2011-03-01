from optparse import make_option

from django.core.management.base import BaseCommand

from amo.utils import chunked
from tags.models import Tag, TagStat
from tags.tasks import update_all_tag_stats

from celery.messaging import establish_connection


class Command(BaseCommand):
    help = 'Migration to repopulate tag stats as per 635118'
    option_list = BaseCommand.option_list + (
        make_option('--delete', action='store_true',
                    dest='delete', help='Deletes all tag counts.'),
    )

    def handle(self, *args, **kw):
        delete = kw.get('delete')
        if delete:
            print "Deleting all tag counts."
            TagStat.objects.all().delete()

        pks = list(Tag.objects.filter(blacklisted=False)
                              .values_list('pk', flat=True).order_by('pk'))
        print "Found: %s tags, adding to celery." % len(pks)
        with establish_connection() as conn:
            for chunk in chunked(pks, 100):
                update_all_tag_stats.delay(chunk)
