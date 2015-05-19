import json
import logging
import os
import shutil
import zipfile

from django.conf import settings
from django.db.models import Q

from celeryutils import task
from lxml import etree

import amo
from addons.models import AddonUser
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
    # We only care about extensions and (complete) themes. The latter is
    # because they may have multi-package XPIs, containing extensions.
    for version in Version.objects.filter(addon_id__in=addon_ids,
                                          addon__type__in=[
                                              amo.ADDON_EXTENSION,
                                              amo.ADDON_THEME]):

        # We only sign files that have been reviewed and are compatible with
        # versions of Firefox that are recent enough.
        to_sign = version.files.filter(ff_version_filter,
                                       status__in=amo.REVIEWED_STATUSES)
        # We only care about multi-package XPIs for themes, because they may
        # have extensions inside.
        if version.addon.type == amo.ADDON_THEME:
            to_sign = version.files.filter(is_multi_package=True)

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
        bump_version = False  # Did we sign at least one file?
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
                bump_version_number(file_obj)
                if file_obj.status == amo.STATUS_PUBLIC:
                    server = settings.SIGNING_SERVER
                else:
                    server = settings.PRELIMINARY_SIGNING_SERVER
                signed = bool(sign_file(file_obj, server))
                if signed:  # Bump the version number if at least one signed.
                    bump_version = True
                else:  # We didn't sign, so revert the version bump.
                    shutil.move(backup_path, file_obj.file_path)
            except:
                log.error(u'Failed signing file {0}'.format(file_obj.pk),
                          exc_info=True)
                # Revert the version bump, restore the backup.
                shutil.move(backup_path, file_obj.file_path)
        # Now update the Version model, if we signed at least one file.
        if bump_version:
            bumped_version = _dot_one(version.version)
            version.update(version=bumped_version,
                           version_int=version_int(bumped_version))
            addon = version.addon
            if addon.pk not in addons_emailed:
                # Send a mail to the owners/devs warning them we've
                # automatically signed their addon.
                qs = (AddonUser.objects
                      .filter(role=amo.AUTHOR_ROLE_OWNER, addon=addon)
                      .exclude(user__email=None))
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


def bump_version_number(file_obj):
    """Add a '.1-signed' to the version number."""
    # Create a new xpi with the bumped version.
    bumped = u'{0}.bumped'.format(file_obj.file_path)
    # Copy the original XPI, with the updated install.rdf or package.json.
    with zipfile.ZipFile(file_obj.file_path, 'r') as source:
        file_list = source.infolist()
        with zipfile.ZipFile(bumped, 'w', zipfile.ZIP_DEFLATED) as dest:
            for file_ in file_list:
                content = source.read(file_.filename)
                if file_.filename == 'install.rdf':
                    content = _bump_version_in_install_rdf(content)
                if file_.filename == 'package.json':
                    content = _bump_version_in_package_json(content)
                dest.writestr(file_, content)
    # Move the bumped file to the original file.
    shutil.move(bumped, file_obj.file_path)


def _dot_one(version):
    """Returns the version with an appended '.1-signed' on it."""
    return u'{0}.1-signed'.format(version)


def _bump_version_in_install_rdf(content):
    """Add a '.1-signed' to the version number in the install.rdf provided."""
    # We need to use an XML parser, and not a RDF parser, because our
    # install.rdf files aren't really standard (they use default namespaces,
    # don't namespace the "about" attribute... rdflib can parse them, and can
    # now even serialize them, but the end result could be very different from
    # the format we need.
    tree = etree.fromstring(content)
    # There's two different formats for the install.rdf: the "standard" one
    # uses nodes for each item (like <em:version>1.2</em:version>), the other
    # alternate one sets attributes on the <RDF:Description
    # RDF:about="urn:mozilla:install-manifest"> element.

    # Get the version node, if it's the common format, or the Description node
    # that has the "em:version" attribute if it's the alternate format.
    namespace = 'http://www.mozilla.org/2004/em-rdf#'
    version_uri = '{{{0}}}version'.format(namespace)
    for node in tree.xpath('//em:version | //*[@em:version]',
                           namespaces={'em': namespace}):
        if node.tag == version_uri:  # Common format, version is a node.
            node.text = _dot_one(node.text)
        else:  # Alternate format, version is an attribute.
            node.set(version_uri, _dot_one(node.get(version_uri)))
    return etree.tostring(tree, xml_declaration=True, encoding='utf-8')


def _bump_version_in_package_json(content):
    """Add a '.1-signed' to the version number in the package.json provided."""
    bumped = json.loads(content)
    if 'version' in bumped:
        bumped['version'] = _dot_one(bumped['version'])
    return json.dumps(bumped)


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
    for version in Version.objects.filter(addon_id__in=addon_ids,
                                          addon__type__in=[
                                              amo.ADDON_EXTENSION,
                                              amo.ADDON_THEME]):
        if not version.version.endswith(bumped_suffix):
            log.info(u'Version {0} was not bumped, skip.'.format(version.pk))
            continue
        to_unsign = version.files.filter(ff_version_filter,
                                         status__in=amo.REVIEWED_STATUSES)
        # We only care about multi-package XPIs for themes, because they may
        # have extensions inside.
        if version.addon.type == amo.ADDON_THEME:
            to_unsign = version.files.filter(is_multi_package=True)

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
                  .exclude(user__email=None))
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
