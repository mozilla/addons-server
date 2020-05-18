import waffle

from celery import chain
from django.conf import settings
from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia import amo
from olympia.amo.decorators import use_primary_db
from olympia.files.utils import lock
from olympia.git.models import GitExtractionEntry
from olympia.git.tasks import (
    continue_git_extraction,
    extract_versions_to_git,
    on_extraction_error,
    remove_git_extraction_entry,
)


log = olympia.core.logger.getLogger('z.git.git_extraction')

# Number of versions to extract in a single task. If you change this value,
# please adjust the soft time limit of the `extract_versions_to_git` task.
# See: https://github.com/mozilla/addons-server/issues/14104
BATCH_SIZE = 10
# Name of the lock() used.
LOCK_NAME = 'git-extraction'
# Name of the waffle switch.
SWITCH_NAME = 'enable-git-extraction-cron'
# The number of entries to process when the command is invoked.
LIMIT = 20


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
            entries = GitExtractionEntry.objects.order_by('-created').all()[
                : options.get('limit', LIMIT)
            ]
            for entry in entries:
                self.extract_addon(entry)

    def extract_addon(self, entry, batch_size=BATCH_SIZE):
        """
        This method takes a GitExtractionEntry object and creates a chain of
        Celery tasks to extract each version in a git repository that haven't
        been extracted yet (including the deleted versions).

        It does not run if the add-on is locked for git extraction.
        """
        addon = entry.addon
        log.info('Starting git extraction of add-on "{}".'.format(addon.pk))

        # See: https://github.com/mozilla/addons-server/issues/14289
        if addon.type != amo.ADDON_EXTENSION:
            log.info(
                'Skipping git extraction of add-on "{}": not an '
                'extension.'.format(addon.pk)
            )
            entry.delete()
            return

        # We cannot use `entry.in_progress` because we have to be sure of the
        # add-on state and `entry` might not reflect the most up-to-date
        # database state here.
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
            .filter(files__is_webextension=True, git_hash='')
            .order_by('created')
            .values_list('pk', flat=True)
        )

        if len(versions_to_extract) == 0:
            log.info(
                'No version to git-extract for add-on "{}", '
                'exiting.'.format(addon.pk)
            )
            # We can safely delete the entry because there is no version to
            # extract.
            entry.delete()
            return

        version_pks = versions_to_extract[0:batch_size]
        tasks = [
            # Create a task to extract the BATCH_SIZE first versions.
            extract_versions_to_git.si(
                addon_pk=addon.pk, version_pks=version_pks
            )
        ]
        if len(version_pks) < len(versions_to_extract):
            # If there are more versions to git-extract, let's keep the entry
            # in the queue until we're done with this entry/add-on. The
            # `continue_git_extraction` task will set the `in_progress` flag to
            # `False` and this CRON task will pick the remaining versions to
            # git-extract the next time it runs.
            tasks.append(continue_git_extraction.si(addon.pk))
        else:
            # If we do not have more versions to git-extract here, we can
            # remove the entry from the queue.
            tasks.append(remove_git_extraction_entry.si(addon.pk))

        log.info(
            'Submitted {} tasks to git-extract {} versions for add-on '
            '"{}".'.format(len(tasks), len(versions_to_extract), addon.pk)
        )
        # Attach an error handler on the chain and run it. The error
        # handler should remove the add-on lock (among other things).
        chain(*tasks).on_error(on_extraction_error.s(addon.pk)).delay()
