import os
import re
import shutil

import olympia.core.logger

from olympia import amo
from olympia.addons.models import AddonUser
from olympia.amo.celery import task
from olympia.files.utils import update_version_number
from olympia.lib.crypto.packaged import SIGN_FOR_APPS, sign_file
from olympia.versions.compare import version_int
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.task')


MAIL_SUBJECT = u'Mozilla Add-ons: {addon} has been automatically signed on AMO'
MAIL_MESSAGE = u"""
Your add-on, {addon}, has been automatically signed for distribution in
upcoming versions of Firefox. The signing process involved re-packaging add-on
files and changing the version string to ensure automatic updates work
correctly. The new versions have kept their review status and are now available
for your users.

We recommend that you give them a try to make sure they don't have any
unexpected problems: {addon_url}

If you are unfamiliar with the extension signing requirement, please read the
following documents:

* Signing announcement:
  http://blog.mozilla.org/addons/2015/02/10/extension-signing-safer-experience/

* Documentation page and FAQ: https://wiki.mozilla.org/Addons/Extension_Signing

If you have any questions or comments on this, please reply to this email or
join #addon-reviewers on irc.mozilla.org.

You're receiving this email because you have an add-on hosted on
https://addons.mozilla.org
"""

MAIL_EXPIRY_SUBJECT = (
    u'Mozilla Add-ons: {addon} has been resigned on AMO')
MAIL_EXPIRY_MESSAGE = u"""
Your add-on, {addon}, has been automatically signed.

We recently discovered a problem with the expiration date of add-on signatures.
As a result, for the next few weeks Firefox will not be able to recognize the
signatures of some add-ons. We are contacting you because your add-on,
{addon}, is affected.

To address this problem, we're signing the affected add-ons again and letting
you know in case you need to deploy this update to your users. The details of
this issue can be found here:

https://bugzilla.mozilla.org/show_bug.cgi?id=1267318

This signing process involved re-packaging add-on files and adding the string
'.1-signed' to their version numbers. If the version number already ended in
'.1-signed', we will increment the number, for example '.1-signed-2'. The
current review status of your add-on will remain the same. Alternatively, you
can upload a new version and have it signed through the usual means.

If you have any questions or need support, please reply to this email or
join #addons on irc.mozilla.org and we'll do our best to help.

You are receiving this email because you have an add-on
on https://addons.mozilla.org
"""

version_regex = re.compile(
    '^(?P<prefix>.*)(?P<version>\.1\-signed)(|\-(?P<number>\d+))$')


def get_new_version_number(version):
    match = version_regex.search(version)
    if not match:
        return u'{}.1-signed'.format(version)
    else:
        num = int(match.groupdict()['number'] or 1)
        return u'{}{}-{}'.format(
            match.groupdict()['prefix'],
            match.groupdict()['version'],
            num + 1)


@task
def sign_addons(addon_ids, force=False, **kw):
    """Used to sign all the versions of an addon.

    This is used in the 'sign_addons' and 'process_addons --task sign_addons'
    management commands.

    It also bumps the version number of the file and the Version, so the
    Firefox extension update mechanism picks this new signed version and
    installs it.
    """
    log.info(u'[{0}] Signing addons.'.format(len(addon_ids)))

    reasons = {
        'default': [MAIL_SUBJECT, MAIL_MESSAGE],
        'expiry': [MAIL_EXPIRY_SUBJECT, MAIL_EXPIRY_MESSAGE]
    }
    mail_subject, mail_message = reasons[kw.get('reason', 'default')]

    addons_emailed = set()
    # We only care about extensions.
    for version in Version.objects.filter(addon_id__in=addon_ids,
                                          addon__type=amo.ADDON_EXTENSION):
        # We only sign files that have been reviewed and are compatible with
        # versions of Firefox that are recent enough.
        to_sign = version.files.filter(
            version__apps__max__application__in=SIGN_FOR_APPS,
            status__in=amo.REVIEWED_STATUSES)

        if force:
            to_sign = to_sign.all()
        else:
            to_sign = to_sign.filter(is_signed=False)
        if not to_sign:
            log.info(u'Not signing addon {0}, version {1} (no files or already'
                     u' signed)'.format(version.addon, version))
        log.info(u'Signing addon {0}, version {1}'.format(version.addon,
                                                          version))
        bumped_version_number = get_new_version_number(version.version)
        signed_at_least_a_file = False  # Did we sign at least one file?
        for file_obj in to_sign:
            if not os.path.isfile(file_obj.file_path):
                log.info(u'File {0} does not exist, skip'.format(file_obj.pk))
                continue
            # Save the original file, before bumping the version.
            backup_path = u'{0}.backup_signature'.format(file_obj.file_path)
            shutil.copy(file_obj.file_path, backup_path)
            try:
                # Need to bump the version (modify manifest file)
                # before the file is signed.
                update_version_number(file_obj, bumped_version_number)
                signed = bool(sign_file(file_obj))
                if signed:  # Bump the version number if at least one signed.
                    signed_at_least_a_file = True
                else:  # We didn't sign, so revert the version bump.
                    shutil.move(backup_path, file_obj.file_path)
            except Exception:
                log.error(u'Failed signing file {0}'.format(file_obj.pk),
                          exc_info=True)
                # Revert the version bump, restore the backup.
                shutil.move(backup_path, file_obj.file_path)
        # Now update the Version model, if we signed at least one file.
        if signed_at_least_a_file:
            version.update(version=bumped_version_number,
                           version_int=version_int(bumped_version_number))
            addon = version.addon
            if addon.pk not in addons_emailed:
                # Send a mail to the owners/devs warning them we've
                # automatically signed their addon.
                qs = (AddonUser.objects
                      .filter(role=amo.AUTHOR_ROLE_OWNER, addon=addon)
                      .exclude(user__email__isnull=True))
                emails = qs.values_list('user__email', flat=True)
                subject = mail_subject.format(addon=addon.name)
                message = mail_message.format(
                    addon=addon.name,
                    addon_url=amo.templatetags.jinja_helpers.absolutify(
                        addon.get_dev_url(action='versions')))
                amo.utils.send_mail(
                    subject, message, recipient_list=emails,
                    headers={'Reply-To': 'amo-admins@mozilla.org'})
                addons_emailed.add(addon.pk)
