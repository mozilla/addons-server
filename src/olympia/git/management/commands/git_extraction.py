import waffle

from celery import chain
from django.conf import settings
from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import chunked
from olympia.files.utils import lock
from olympia.git.models import GitExtractionEntry
from olympia.git.tasks import (
    extract_versions_to_git,
    on_extraction_error,
    remove_git_extraction_entry,
)


log = olympia.core.logger.getLogger('z.git.git_extraction')

BATCH_SIZE = 10  # Number of versions to extract in a single task.
LOCK_NAME = 'git-extraction'  # Name of the lock() used.
SWITCH_NAME = 'enable-git-extraction-cron'  # Name of the waffle switch.


class Command(BaseCommand):
    help = 'Extract add-on versions into Git repositories'

    @use_primary_db
    def handle(self, *args, **options):
        if not waffle.switch_is_active(SWITCH_NAME):
            log.info(
                'Not running git_extraction command because switch "{}" is '
                'not active.'.format(SWITCH_NAME)
            )
            return

        # Get a lock before doing anything, we don't want to have multiple
        # instances of the command running in parallel.
        with lock(settings.TMP_PATH, LOCK_NAME) as lock_attained:
            if not lock_attained:
                # We didn't get the lock...
                log.error('{} lock present, aborting.'.format(LOCK_NAME))
                return

            # If an add-on ID is present more than once, the `extract_addon()`
            # method will skip all but the first occurrence because the add-on
            # will be locked for git extraction.
            entries = GitExtractionEntry.objects.order_by('created').all()
            for entry in entries:
                self.extract_addon(entry)

    def extract_addon(self, entry):
        """
        This method takes a GitExtractionEntry object and creates a chain of
        Celery tasks to extract each version in a git repository that haven't
        been extracted yet (including the deleted versions).

        It does not run if the add-on is locked for git extraction.
        """
        addon = entry.addon
        log.info('Starting extraction of add-on "{}".'.format(addon.pk))

        if addon.git_extraction_is_in_progress:
            log.info(
                'Aborting extraction of addon "{}" to git storage '
                'because it is already in progress.'.format(addon.pk)
            )
            return

        log.info('Locking add-on "{}" before extraction.'.format(addon.pk))
        entry.update(in_progress=True)

        # Retrieve all the version pks to extract, sorted by creation date.
        versions_to_extract = (
            addon.versions(manager='unfiltered_for_relations')
            .filter(git_hash='')
            .order_by('created')
            .values_list('pk', flat=True)
        )

        if len(versions_to_extract) == 0:
            log.info(
                'No version to extract for add-on "{}", '
                'exiting.'.format(addon.pk)
            )
            # We can safely delete the entry because there is no version to
            # extract.
            entry.delete()
            return

        tasks = []
        for version_pks in chunked(versions_to_extract, BATCH_SIZE):
            # Create a task to extract a subset of versions.
            tasks.append(
                extract_versions_to_git.si(
                    addon_pk=addon.pk, version_pks=version_pks
                )
            )
        tasks.append(remove_git_extraction_entry.si(addon.pk))

        log.info(
            'Submitted {} tasks to extract {} versions for add-on '
            '"{}".'.format(len(tasks), len(versions_to_extract), addon.pk)
        )
        # Attach an error handler on the chain and run it. The error
        # handler should remove the add-on lock (among other things).
        chain(*tasks).on_error(on_extraction_error.s(addon.pk)).delay()
