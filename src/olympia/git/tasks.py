from django_statsd.clients import statsd

import olympia.core.logger
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db

from .models import GitExtractionEntry
from .utils import (
    AddonGitRepository,
    BrokenRefError,
    MissingMasterBranchError,
    extract_version_to_git,
)


log = olympia.core.logger.getLogger('z.git.task')


@task
@use_primary_db
def remove_git_extraction_entry(addon_pk):
    log.info('Removing add-on "%s" from the git extraction queue.', addon_pk)
    GitExtractionEntry.objects.filter(addon_id=addon_pk, in_progress=True).delete()


@task
@use_primary_db
def continue_git_extraction(addon_pk):
    log.info(
        'Keeping add-on "%s" in the git extraction queue because there are '
        'still versions to git-extract.',
        addon_pk,
    )
    GitExtractionEntry.objects.filter(addon_id=addon_pk, in_progress=True).update(
        in_progress=False
    )


@task
@use_primary_db
def on_extraction_error(request, exc, traceback, addon_pk):
    log.error('Git extraction failed for add-on "%s".', addon_pk)

    # We only handle *some* errors here because we cannot apply the same
    # approach to recover from all possible errors. Our current technique to
    # repair the errors below is to delete the git repository and let the
    # add-on be re-extracted later.
    delete_repo = False

    # See: https://github.com/mozilla/addons-server/issues/13590
    if isinstance(exc, BrokenRefError):
        delete_repo = True
        log.warning(
            'Deleting the git repository for add-on "%s" because we detected '
            'a broken reference.',
            addon_pk,
        )
        statsd.incr('git.extraction.error.broken_ref')
    # See: https://github.com/mozilla/addons-server/issues/14127
    if isinstance(exc, MissingMasterBranchError):
        delete_repo = True
        log.warning(
            'Deleting the git repository for add-on "%s" because the "master" '
            'branch is missing.',
            addon_pk,
        )
        statsd.incr('git.extraction.error.missing_master_branch')

    if delete_repo:
        # Retrieve the repo for the add-on and delete it.
        addon_repo = AddonGitRepository(addon_pk, package_type='addon')
        # If the repository is too recent, it might be because of a
        # git-extraction (infinite) loop.
        if addon_repo.is_recent:
            # Log an error so that we can investigate later.
            log.error(
                'Not deleting git repository for add-on "%s" because it '
                'was created less than 1 hour ago',
                addon_pk,
            )
            statsd.incr('git.extraction.error.extraction_loop')
        else:
            addon_repo.delete()
            log.info('Deleted git repository for add-on "%s".', addon_pk)
            # Create a new git extraction entry.
            GitExtractionEntry.objects.create(addon_id=addon_pk)
            log.info('Added add-on "%s" to the git extraction queue.', addon_pk)

    remove_git_extraction_entry(addon_pk)


@task
@use_primary_db
def extract_versions_to_git(addon_pk, version_pks):
    log.info(
        'Starting the git extraction of %s versions for add-on "%s".',
        len(version_pks),
        addon_pk,
    )
    for version_pk in version_pks:
        extract_version_to_git(version_id=version_pk)
