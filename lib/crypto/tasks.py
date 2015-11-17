import logging
import os
import shutil

from django.conf import settings
from django.db.models import Q

import amo
from addons.models import AddonUser
from amo.celery import task
from files.utils import update_version_number
from lib.crypto.packaged import sign_file
from versions.compare import version_int
from versions.models import Version

log = logging.getLogger('z.task')


MAIL_SUBJECT = u'Mozilla Add-ons: {addon} has been automatically signed on AMO'
MAIL_MESSAGE = u"""
Your add-on, {addon}, has been automatically signed for distribution in
upcoming versions of Firefox. The signing process involved repackaging the
add-on files and adding the string '.1-signed' to their versions numbers. The
new versions have kept their review status and are now available for your
users.
We recommend that you give them a try to make sure they don't have any
unexpected problems: {addon_url}

If you are unfamiliar with the extension signing requirement, please read the
following documents:

* Signing announcement:
  http://blog.mozilla.org/addons/2015/02/10/extension-signing-safer-experience/

* Documentation page and FAQ: https://wiki.mozilla.org/Addons/Extension_Signing

If you have any questions or comments on this, please reply to this email or
join #amo-editors on irc.mozilla.org.

You're receiving this email because you have an add-on hosted on
https://addons.mozilla.org
"""

MAIL_UNSIGN_SUBJECT = u'Mozilla Add-ons: {addon} has been unsigned/reverted'
MAIL_UNSIGN_MESSAGE = u"""
Your add-on, {addon}, was automatically signed for distribution in upcoming
versions of Firefox. However, we encountered an issue with older versions of
Firefox, and had to revert this signature. We restored the backups we had for
the signed versions.
We recommend that you give them a try to make sure they don't have any
unexpected problems: {addon_url}

Link to the bug: https://bugzilla.mozilla.org/show_bug.cgi?id=1158467

If you have any questions or comments on this, please reply to this email or
join #amo-editors on irc.mozilla.org.

You're receiving this email because you have an add-on hosted on
https://addons.mozilla.org and we had automatically signed it.
"""


@task
def sign_addons(addon_ids, force=False, **kw):
    """Used to sign all the versions of an addon.

    This is used in the 'sign_addons' and 'process_addons --task sign_addons'
    management commands.

    It also bumps the version number of the file and the Version, so the
    Firefox extension update mecanism picks this new signed version and
    installs it.
    """
    log.info(u'[{0}] Signing addons.'.format(len(addon_ids)))

    def file_supports_firefox(version):
        """Return a Q object: files supporting at least a firefox version."""
        return Q(version__apps__max__application=amo.FIREFOX.id,
                 version__apps__max__version_int__gte=version_int(version))

    is_default_compatible = Q(binary_components=False,
                              strict_compatibility=False)
    # We only want to sign files that are at least compatible with Firefox
    # MIN_D2C_VERSION, or Firefox MIN_NOT_D2C_VERSION if they are not default
    # to compatible.
    # The signing feature should be supported from Firefox 40 and above, but
    # we're still signing some files that are a bit older just in case.
    ff_version_filter = (
        (is_default_compatible &
            file_supports_firefox(settings.MIN_D2C_VERSION)) |
        (~is_default_compatible &
            file_supports_firefox(settings.MIN_NOT_D2C_VERSION)))

    addons_emailed = []
    # We only care about extensions.
    for version in Version.objects.filter(addon_id__in=addon_ids,
                                          addon__type=amo.ADDON_EXTENSION):
        # We only sign files that have been reviewed and are compatible with
        # versions of Firefox that are recent enough.
        to_sign = version.files.filter(ff_version_filter,
                                       status__in=amo.REVIEWED_STATUSES)

        if force:
            to_sign = to_sign.all()
        else:
            to_sign = to_sign.filter(is_signed=False)
        if not to_sign:
            log.info(u'Not signing addon {0}, version {1} (no files or already'
                     u' signed)'.format(version.addon, version))
            continue
        log.info(u'Signing addon {0}, version {1}'.format(version.addon,
                                                          version))
        bumped_version_number = u'{0}.1-signed'.format(version.version)
        signed_at_least_a_file = False  # Did we sign at least one file?
        for file_obj in to_sign:
            if not os.path.isfile(file_obj.file_path):
                log.info(u'File {0} does not exist, skip'.format(file_obj.pk))
                continue
            # Save the original file, before bumping the version.
            backup_path = u'{0}.backup_signature'.format(file_obj.file_path)
            shutil.copy(file_obj.file_path, backup_path)
            try:
                # Need to bump the version (modify install.rdf or package.json)
                # before the file is signed.
                update_version_number(file_obj, bumped_version_number)
                if file_obj.status == amo.STATUS_PUBLIC:
                    server = settings.SIGNING_SERVER
                else:
                    server = settings.PRELIMINARY_SIGNING_SERVER
                signed = bool(sign_file(file_obj, server))
                if signed:  # Bump the version number if at least one signed.
                    signed_at_least_a_file = True
                else:  # We didn't sign, so revert the version bump.
                    shutil.move(backup_path, file_obj.file_path)
            except:
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
                subject = MAIL_SUBJECT.format(addon=addon.name)
                message = MAIL_MESSAGE.format(
                    addon=addon.name,
                    addon_url=amo.helpers.absolutify(
                        addon.get_dev_url(action='versions')))
                amo.utils.send_mail(
                    subject, message, recipient_list=emails,
                    fail_silently=True,
                    headers={'Reply-To': 'amo-editors@mozilla.org'})
                addons_emailed.append(addon.pk)


@task
def unsign_addons(addon_ids, force=False, **kw):
    """Used to unsign all the versions of an addon that were previously signed.

    This is used to revert the signing in case we need to.

    It first moves the backup of the signed file back over its original one,
    then un-bump the version, and finally re-hash the file.
    """
    log.info(u'[{0}] Unsigning addons.'.format(len(addon_ids)))
    bumped_suffix = u'.1-signed'

    def file_supports_firefox(version):
        """Return a Q object: files supporting at least a firefox version."""
        return Q(version__apps__max__application=amo.FIREFOX.id,
                 version__apps__max__version_int__gte=version_int(version))

    is_default_compatible = Q(binary_components=False,
                              strict_compatibility=False)
    # We only want to unsign files that are at least compatible with Firefox
    # MIN_D2C_VERSION, or Firefox MIN_NOT_D2C_VERSION if they are not default
    # to compatible.
    # The signing feature should be supported from Firefox 40 and above, but
    # we're still signing some files that are a bit older just in case.
    ff_version_filter = (
        (is_default_compatible &
            file_supports_firefox(settings.MIN_D2C_VERSION)) |
        (~is_default_compatible &
            file_supports_firefox(settings.MIN_NOT_D2C_VERSION)))

    addons_emailed = []
    # We only care about extensions and themes which are multi-package XPIs.
    # We don't sign multi-package XPIs since bug 1172696, but we had signed
    # some before that, and we now have to deal with it, eg for bug 1205823.
    for version in Version.objects.filter(addon_id__in=addon_ids,
                                          addon__type__in=[
                                              amo.ADDON_EXTENSION,
                                              amo.ADDON_THEME]):
        # We only unsign files that have been reviewed and are compatible with
        # versions of Firefox that are recent enough.
        if not version.version.endswith(bumped_suffix):
            log.info(u'Version {0} was not bumped, skip.'.format(version.pk))
            continue
        to_unsign = version.files.filter(ff_version_filter,
                                         status__in=amo.REVIEWED_STATUSES)

        # We only care about multi-package XPIs for themes, because they may
        # have extensions inside.
        if version.addon.type == amo.ADDON_THEME:
            to_unsign = to_unsign.files.filter(is_multi_package=True)

        if force:
            to_unsign = to_unsign.all()
        else:
            to_unsign = to_unsign.filter(is_signed=False)
        if not to_unsign:
            log.info(u'Not unsigning addon {0}, version {1} (no files or not '
                     u'signed)'.format(version.addon, version))
            continue
        log.info(u'Unsigning addon {0}, version {1}'.format(version.addon,
                                                            version))
        for file_obj in to_unsign:
            if not os.path.isfile(file_obj.file_path):
                log.info(u'File {0} does not exist, skip'.format(file_obj.pk))
                continue
            backup_path = u'{0}.backup_signature'.format(file_obj.file_path)
            if not os.path.isfile(backup_path):
                log.info(u'Backup {0} does not exist, skip'.format(
                    backup_path))
                continue
            # Restore the backup.
            shutil.move(backup_path, file_obj.file_path)
            file_obj.update(cert_serial_num='', hash=file_obj.generate_hash())
        # Now update the Version model, to unbump its version.
        unbumped_version = version.version[:-len(bumped_suffix)]
        version.update(version=unbumped_version,
                       version_int=version_int(unbumped_version))
        # Warn addon owners that we restored backups.
        addon = version.addon
        if addon.pk not in addons_emailed:
            # Send a mail to the owners/devs warning them we've
            # unsigned their addon and restored backups.
            qs = (AddonUser.objects
                  .filter(role=amo.AUTHOR_ROLE_OWNER, addon=addon)
                  .exclude(user__email__isnull=True))
            emails = qs.values_list('user__email', flat=True)
            subject = MAIL_UNSIGN_SUBJECT.format(addon=addon.name)
            message = MAIL_UNSIGN_MESSAGE.format(
                addon=addon.name,
                addon_url=amo.helpers.absolutify(
                    addon.get_dev_url(action='versions')))
            amo.utils.send_mail(
                subject, message, recipient_list=emails,
                fail_silently=True,
                headers={'Reply-To': 'amo-editors@mozilla.org'})
            addons_emailed.append(addon.pk)
