from datetime import datetime

import waffle
from django_statsd.clients import statsd

import olympia.core.logger
from olympia import amo
from olympia.constants.blocklist import MLBF_BASE_ID_CONFIG_KEY, MLBF_TIME_CONFIG_KEY
from olympia.versions.models import Version
from olympia.zadmin.models import get_config

from .mlbf import MLBF
from .models import Block, BlocklistSubmission
from .tasks import cleanup_old_files, process_blocklistsubmission, upload_filter
from .utils import datetime_to_ts


log = olympia.core.logger.getLogger('z.cron')


def get_blocklist_last_modified_time():
    latest_block = Block.objects.order_by('-modified').first()
    return datetime_to_ts(latest_block.modified) if latest_block else 0


def upload_mlbf_to_remote_settings(*, bypass_switch=False, force_base=False):
    """Creates a bloomfilter, and possibly a stash json blob, and uploads to
    remote-settings.
    bypass_switch=<Truthy value> will bypass the "blocklist_mlbf_submit" switch
    for manual use/testing.
    force_base=<Truthy value> will force a new base MLBF and a reset of the
    collection.
    """
    bypass_switch = bool(bypass_switch)
    if not (bypass_switch or waffle.switch_is_active('blocklist_mlbf_submit')):
        log.info('Upload MLBF to remote settings cron job disabled.')
        return
    with statsd.timer('blocklist.cron.upload_mlbf_to_remote_settings'):
        _upload_mlbf_to_remote_settings(force_base=bool(force_base))
    statsd.incr('blocklist.cron.upload_mlbf_to_remote_settings.success')


def _upload_mlbf_to_remote_settings(*, force_base=False):
    last_generation_time = get_config(MLBF_TIME_CONFIG_KEY, 0, json_value=True)

    log.info('Starting Upload MLBF to remote settings cron job.')

    # This timestamp represents the point in time when all previous addon
    # guid + versions and blocks were used to generate the bloomfilter.
    # An add-on version/file from before this time will definitely be accounted
    # for in the bloomfilter so we can reliably assert if it's blocked or not.
    # An add-on version/file from after this time can't be reliably asserted -
    # there may be false positives or false negatives.
    # https://github.com/mozilla/addons-server/issues/13695
    generation_time = datetime_to_ts()
    mlbf = MLBF.generate_from_db(generation_time)
    previous_filter = MLBF.load_from_storage(last_generation_time)

    changes_count = mlbf.blocks_changed_since_previous(previous_filter)
    statsd.incr(
        'blocklist.cron.upload_mlbf_to_remote_settings.blocked_changed', changes_count
    )
    need_update = (
        force_base
        or last_generation_time < get_blocklist_last_modified_time()
        or changes_count
    )
    if not need_update:
        log.info('No new/modified/deleted Blocks in database; skipping MLBF generation')
        return

    statsd.incr(
        'blocklist.cron.upload_mlbf_to_remote_settings.blocked_count',
        len(mlbf.blocked_items),
    )
    statsd.incr(
        'blocklist.cron.upload_mlbf_to_remote_settings.not_blocked_count',
        len(mlbf.not_blocked_items),
    )

    base_filter_id = get_config(MLBF_BASE_ID_CONFIG_KEY, 0, json_value=True)
    # optimize for when the base_filter was the previous generation so
    # we don't have to load the blocked JSON file twice.
    base_filter = (
        MLBF.load_from_storage(base_filter_id)
        if last_generation_time != base_filter_id
        else previous_filter
    )

    make_base_filter = (
        force_base or not base_filter_id or mlbf.should_reset_base_filter(base_filter)
    )

    if last_generation_time and not make_base_filter:
        try:
            mlbf.generate_and_write_stash(previous_filter)
        except FileNotFoundError:
            log.info("No previous blocked.json so we can't create a stash.")
            # fallback to creating a new base if stash fails
            make_base_filter = True
    if make_base_filter:
        mlbf.generate_and_write_filter()

    upload_filter.delay(generation_time, is_base=make_base_filter)

    if base_filter_id:
        cleanup_old_files.delay(base_filter_id=base_filter_id)


def process_blocklistsubmissions():
    submissions = list(
        BlocklistSubmission.objects.filter(
            signoff_state__in=BlocklistSubmission.SIGNOFF_STATES_APPROVED,
            delayed_until__lte=datetime.now(),
        )
    )
    # collect all the versions in one query for efficiency
    all_version_ids = [
        vid
        for sub in submissions
        for vid in sub.changed_version_ids
        if sub.from_reviewer_tools
    ]
    all_versions = list(
        Version.unfiltered.filter(id__in=all_version_ids)
        .select_related('reviewerflags')
        .no_transforms()
        if all_version_ids
        else ()
    )
    for sub in submissions:
        if sub.from_reviewer_tools:
            # This submission has to wait for a delayed rejection
            # First, check if some of the versions are not rejected and have had the
            # pending rejection flag cleared. If so remove them from the submission
            ids_cleared_pending_rejection = {
                ver.id
                for ver in all_versions
                if ver.id in sub.changed_version_ids
                and not ver.pending_rejection
                and ver.file.status != amo.STATUS_DISABLED
            }
            if ids_cleared_pending_rejection:
                if ids_cleared_pending_rejection == set(sub.changed_version_ids):
                    # if all the versions have been cleared, just delete the submission
                    sub.delete()
                    # nothing to do any longer
                    continue
                else:
                    # otherwise drop just those versions from the submission
                    sub.update(
                        changed_version_ids=sorted(
                            set(sub.changed_version_ids) - ids_cleared_pending_rejection
                        )
                    )

            # if there are still versions pending rejection we skip and try later
            if any(
                version.pending_rejection
                for version in all_versions
                if version.id in sub.changed_version_ids
            ):
                continue
            # otherwise we're good to proccess the submission into Blocks

        process_blocklistsubmission.delay(sub.id)
