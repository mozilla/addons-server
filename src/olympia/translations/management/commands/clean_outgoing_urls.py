# -*- coding: utf-8 -*-
from celery import group
from django.core.management.base import BaseCommand
from olympia.amo.utils import chunked

from olympia.addons.models import Addon
from olympia.bandwagon.models import CollectionAddon
from olympia.translations.tasks import clean_outgoing_urls
from olympia.versions.models import Version, License


class Command(BaseCommand):
    help = 'Clean up any old outgoing urls from the translations table.'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--dry-run', action='store_true', dest='dry_run',
            help='Run this command without applying the results to the database.')


    def purified_translations(self):
        """Retrieve a list of ids for fields that fall under the PurifiedField class"""
        # Addon
        id_list = list(Addon.objects.filter(description_id__isnull=False).values_list('description_id', flat=True))
        id_list.extend(list(Addon.objects.filter(developer_comments_id__isnull=False).values_list('developer_comments_id', flat=True)))
        id_list.extend(list(Addon.objects.filter(eula_id__isnull=False).values_list('eula_id', flat=True)))
        id_list.extend(list(Addon.objects.filter(privacy_policy_id__isnull=False).values_list('privacy_policy_id', flat=True)))

        # Version
        id_list.extend(list(Version.objects.filter(releasenotes_id__isnull=False).values_list('releasenotes_id', flat=True)))

        return id_list


    def linkified_translations(self):
        """Retrieve a list of ids for fields that fall under the LinkifiedField class"""
        # Addon
        id_list = list(Addon.objects.filter(summary_id__isnull=False).values_list('summary_id', flat=True))

        # Collection Addon
        id_list.extend(list(CollectionAddon.objects.filter(comments_id__isnull=False).values_list('comments_id', flat=True)))

        # License
        id_list.extend(list(License.objects.filter(text_id__isnull=False).values_list('text_id', flat=True)))

        return id_list


    def handle(self, *args, **options):
        ids_dict = {
            'purified': self.purified_translations(),
            'linkified': self.linkified_translations(),
        }

        tasks = []
        for meta_type, ids in ids_dict.items():
            tasks.extend([clean_outgoing_urls.subtask(args=[chunk, meta_type, options['dry_run']])
                     for chunk in chunked(ids, 100)])

        group(tasks).apply_async()
