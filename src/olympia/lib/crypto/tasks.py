import json
import os
import zipfile

from django.conf import settings
from django.db import transaction
from django.utils import translation

import olympia.core.logger
from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonUser
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.files.models import FileUpload
from olympia.files.utils import ManifestJSONExtractor, parse_addon
from olympia.lib.crypto.signing import sign_file
from olympia.users.utils import get_task_user
from olympia.versions.compare import VersionString
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.crypto.tasks')


MAIL_COSE_SUBJECT = 'Your Firefox add-on {addon} has been re-signed'

MAIL_COSE_MESSAGE = """
Greetings from the Mozilla Add-ons Team!

Per our previous communication, this email is to confirm that the most recent
publicly available version of your add-on, {addon}, has now been re-signed with
a stronger signature for a more secure add-ons ecosystem. It will remain
backwards compatible with previous versions of Firefox.

Please be aware that to re-sign add-ons automatically we had to clone the
latest public version of your add-on, bump the version number and then re-sign,
so don't be alarmed if you see that your add-on's version number has increased.

Please feel free to reply to this email if you have any questions.

Regards,
Mozilla Add-ons Team
"""  # noqa: E501


def get_new_version_number(version):
    # Parse existing version number, increment the last part, and replace
    # the suffix with "resigned1", in order to get a new version number that
    # would force existing users to upgrade while making it explicit this is
    # an automatic re-sign. For example, '1.0' would return '1.1resigned1'.
    vs = VersionString(version)
    parts = vs.vparts
    # We're always incrementing the last "number".
    parts[-1].a += 1
    # The "suffix" is always "resigned1" (potentially overriding whatever was
    # there).
    parts[-1].b = 'resigned'
    parts[-1].c = 1
    parts[-1].d = ''
    return VersionString('.'.join(str(part) for part in parts))


def update_version_in_json_manifest(content, new_version_number):
    """Change the version number in the json manifest file provided."""
    json_data = ManifestJSONExtractor(content).data
    json_data['version'] = new_version_number
    return json.dumps(json_data, indent=2)


def copy_xpi_with_new_version_number(src, dst, new_version_number):
    """Copy a xpi while bumping its version number in the manifest."""
    # We can't modify the contents of a zipfile in-place, so instead of copying
    # the old zip file and modifying it, we open the old one, copy the contents
    # of each file it contains to the new one, altering the manifest.json when
    # we run into it.
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with zipfile.ZipFile(src, 'r') as source:
        file_list = source.infolist()
        with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as dest:
            for file_ in file_list:
                content = source.read(file_.filename)
                if file_.filename == 'manifest.json':
                    content = update_version_in_json_manifest(
                        content, new_version_number
                    )
                dest.writestr(file_, content)


@task
@use_primary_db
def bump_and_resign_addons(addon_ids):
    """Used to bump and resign the current version of specified add-ons..

    This is used in the 'process_addons --task bump_and_resign_addons'
    management command.

    It creates a new version from the current version, bumping the version
    number inside the manifest and on the version instance, and that new
    version replaces the current version, so the Firefox extension update
    mechanism will pick this new signed version up and will install it.
    """
    log.info(
        'Bumping and re-signing addons. %s-%s [%d].',
        addon_ids[0],
        addon_ids[-1],
        len(addon_ids),
    )

    current_versions = Addon.objects.filter(id__in=addon_ids).values_list(
        '_current_version', flat=True
    )
    qs = Version.objects.filter(id__in=current_versions)

    with translation.override(settings.LANGUAGE_CODE):
        for old_version in qs:
            bump_addon_version(old_version)


def duplicate_addon_version(old_version, new_version_number, user):
    addon = old_version.addon
    old_file_obj = old_version.file
    carryover_groups = [
        promotion
        for promotion in addon.promoted_groups()
        if promotion.listed_pre_review
    ]
    # We only sign files that have been reviewed
    if old_file_obj.status not in amo.APPROVED_STATUSES:
        log.info(
            'Not signing addon {}, version {} (no files)'.format(
                old_version.addon, old_version
            )
        )
        return

    if not old_file_obj.file or not os.path.isfile(old_file_obj.file.path):
        log.info(f'File {old_file_obj.pk} does not exist, skip')
        return

    old_validation = (
        old_file_obj.validation.validation if old_file_obj.has_been_validated else None
    )

    try:
        # Copy the original file to a new FileUpload.
        original_author = addon.authors.first()
        upload = FileUpload.objects.create(
            addon=addon,
            version=new_version_number,
            user=user,
            channel=old_version.channel,
            source=amo.UPLOAD_SOURCE_GENERATED,
            ip_address=user.last_login_ip,
            validation=old_validation,
        )
        upload.name = f'{upload.uuid.hex}_{new_version_number}.zip'
        upload.path = upload.generate_path('.zip')
        upload.valid = True
        upload.save()

        # Create the xpi with the bumped version number.
        copy_xpi_with_new_version_number(
            old_file_obj.file.path, upload.file_path, new_version_number
        )

        # Parse the add-on. We use the original author of the add-on, not
        # the task user, in case they have special permissions allowing
        # the original version to be submitted.
        parsed_data = parse_addon(
            upload, addon=addon, user=original_author, bypass_name_checks=True
        )
        parsed_data['approval_notes'] = old_version.approval_notes

        with transaction.atomic():
            # Create a version object out of the FileUpload + parsed data.
            new_version = Version.from_upload(
                upload,
                old_version.addon,
                compatibility=old_version.compatible_apps,
                channel=old_version.channel,
                parsed_data=parsed_data,
            )

            # Sign it (may raise SigningError).
            sign_file(new_version.file)

            # Approve it.
            new_version.file.update(
                approval_date=new_version.file.created,
                datestatuschanged=new_version.file.created,
                status=amo.STATUS_APPROVED,
            )

            # Carry over promotion if necessary.
            if carryover_groups:
                addon.approve_for_version(new_version, carryover_groups)

    except Exception:
        log.exception(f'Failed re-signing file {old_file_obj.pk}', exc_info=True)
        # Next loop iteration will clear the task queue.
        return
    return new_version


def bump_addon_version(old_version):
    mail_subject, mail_message = MAIL_COSE_SUBJECT, MAIL_COSE_MESSAGE
    task_user = get_task_user()
    # last login ip should already be set in the database even on the
    # task user, but in case it's not, like in tests/local envs, set it
    # on the instance, forcing it to be localhost, that should be
    # enough for our needs.
    task_user.last_login_ip = '127.0.0.1'
    bumped_version_number = get_new_version_number(old_version.version)

    log.info(f'Bumping addon {old_version.addon}, version {old_version}')
    new_version = duplicate_addon_version(old_version, bumped_version_number, task_user)
    if not new_version:
        return

    # Now notify the developers of that add-on. Any exception should have
    # caused an early return before reaching this point.
    addon = old_version.addon
    ActivityLog.objects.create(
        amo.LOG.VERSION_RESIGNED,
        addon,
        new_version,
        str(old_version.version),
        user=task_user,
    )
    # Send a mail to the owners warning them we've automatically created and
    # signed a new version of their addon.
    qs = AddonUser.objects.filter(role=amo.AUTHOR_ROLE_OWNER, addon=addon).exclude(
        user__email__isnull=True
    )
    subject = mail_subject.format(addon=addon.name)
    message = mail_message.format(addon=addon.name)
    for email in qs.values_list('user__email', flat=True).order_by('user__pk'):
        amo.utils.send_mail(
            subject,
            message,
            reply_to=['mozilla-add-ons-community@mozilla.com'],
            recipient_list=[email],
        )
