import os
import shutil

import olympia.core.logger
from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonUser
from olympia.amo.celery import task
from olympia.files.utils import update_version_number
from olympia.lib.crypto.signing import sign_file
from olympia.users.utils import get_task_user
from olympia.versions.compare import VersionString
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.task')


MAIL_COSE_SUBJECT = (
    'Your Firefox extension has been re-signed with a stronger signature'
)

MAIL_COSE_MESSAGE = """
Hello,

Mozilla has recently upgraded the signing [1] for Firefox extensions, themes,
dictionaries, and langpacks to provide a stronger signature. All add-on
versions uploaded to addons.mozilla.org after April 5, 2019 have this
signature. We plan to stop accepting the old signature with Firefox 70 [2].

The current version of your add-on, {addon}, listed on addons.mozilla.org has
been automatically re-signed with the stronger signature. Your add-on will
remain backwards compatible with previous versions of Firefox, including ESR 68
[3], and will continue working when your users upgrade to Firefox 70.

You do not need to take any action at this time.

Regards,

The Add-ons Team

---
[1] https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/
[2] https://wiki.mozilla.org/Release_Management/Calendar
[3] https://www.mozilla.org/firefox/enterprise/
--

You have received this email because you are a registered developer of a
Firefox add-on. If you do not want to receive these updates regarding your
add-on, please sign in to addons.mozilla.org and delete your add-on(s).
"""  # noqa: E501


def get_new_version_number(version):
    # Parse existing version number, increment the last part, and replace
    # the suffix with "resigned1", in order to get a new version number that
    # would force existing users to upgrade.
    # Example: '1.0' would return '1.1resigned1'.
    vs = VersionString(version)
    parts = vs.vparts
    parts[-1].a += 1
    parts[-1].b = 'resigned'
    parts[-1].c = 1
    return str(VersionString.from_vparts(parts))


@task
def sign_addons(addon_ids, force=False, send_emails=True, **kw):
    """Used to sign all the versions of an addon.

    This is used in the 'process_addons --task resign_addons_for_cose'
    management command.

    This is also used to resign some promoted addons after they've been added
    to a group (or paid).

    It also bumps the version number of the file and the Version, so the
    Firefox extension update mechanism picks this new signed version and
    installs it.
    """
    log.info(f'[{len(addon_ids)}] Signing addons.')

    mail_subject, mail_message = MAIL_COSE_SUBJECT, MAIL_COSE_MESSAGE

    # query everything except for search-plugins as they're generally
    # not signed
    current_versions = Addon.objects.filter(id__in=addon_ids).values_list(
        '_current_version', flat=True
    )
    qset = Version.objects.filter(id__in=current_versions)

    addons_emailed = set()
    task_user = get_task_user()

    for version in qset:
        file_obj = version.file
        # We only sign files that have been reviewed
        if file_obj.status not in amo.APPROVED_STATUSES:
            log.info(
                'Not signing addon {}, version {} (no files)'.format(
                    version.addon, version
                )
            )
            continue

        log.info(f'Signing addon {version.addon}, version {version}')
        bumped_version_number = get_new_version_number(version.version)
        did_sign = False  # Did we sign at the file?

        if not file_obj.file or not os.path.isfile(file_obj.file.path):
            log.info(f'File {file_obj.pk} does not exist, skip')
            continue

        # FIXME: we want to change this and create a new version instead.
        # In the past to do this we created a whole fileupload, ran
        # Version.from_upload(), then manually approved it.
        # Note that we want a custom email, so we probably shouldn't go through
        # ReviewHelper... unless it can easily be customized ? Just sign and
        # set to APPROVED. Make sure datestatuschanged, approval_date are set
        # to now as well.

        try:
            # Save the original file, before bumping the version.
            backup_path = f'{file_obj.file.path}.backup_signature'
            shutil.copy(file_obj.file.path, backup_path)
            # Need to bump the version (modify manifest file)
            # before the file is signed.
            update_version_number(file_obj, bumped_version_number)
            did_sign = bool(sign_file(file_obj))
            if not did_sign:  # We didn't sign, so revert the version bump.
                shutil.move(backup_path, file_obj.file.path)
        except Exception:
            log.error(f'Failed signing file {file_obj.pk}', exc_info=True)
            # Revert the version bump, restore the backup.
            shutil.move(backup_path, file_obj.file.path)

        # Now update the Version model, if we signed at least one file.
        if did_sign:
            previous_version_str = str(version.version)
            version.update(version=bumped_version_number)
            addon = version.addon
            ActivityLog.objects.create(
                amo.LOG.VERSION_RESIGNED,
                addon,
                version,
                previous_version_str,
                user=task_user,
            )
            if send_emails and addon.pk not in addons_emailed:
                # Send a mail to the owners/devs warning them we've
                # automatically signed their addon.
                qs = AddonUser.objects.filter(
                    role=amo.AUTHOR_ROLE_OWNER, addon=addon
                ).exclude(user__email__isnull=True)
                emails = qs.values_list('user__email', flat=True)
                subject = mail_subject
                message = mail_message.format(addon=addon.name)
                amo.utils.send_mail(
                    subject,
                    message,
                    recipient_list=emails,
                    headers={'Reply-To': 'amo-admins@mozilla.com'},
                )
                addons_emailed.add(addon.pk)
