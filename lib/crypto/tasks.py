import json
import logging
import os
import shutil
import zipfile

from celeryutils import task
from lxml import etree

import amo
from versions.models import Version
from lib.crypto.packaged import sign_file

log = logging.getLogger('z.task')


@task
def sign_addons(addon_ids, force=False, **kw):
    """Used to sign all the versions of an addon.

    This is used in the 'sign_addons' and 'process_addons --task sign_addons'
    management commands.

    It also bumps the version number of the file and the Version, so the
    Firefox extension update mecanism picks this new signed version and
    installs it.
    """
    log.info('[{0}] Signing addons.'.format(len(addon_ids)))
    for version in Version.objects.filter(addon_id__in=addon_ids,
                                          addon__type=amo.ADDON_EXTENSION):
        if force:
            to_sign = version.files.all()
        else:
            to_sign = [f for f in version.files.all() if not f.is_signed]
        if not to_sign:
            log.info('Not signing addon {0}, version {1} (no files or already '
                     'signed)'.format(version.addon, version))
            continue
        log.info('Signing addon {0}, version {1}'.format(version.addon,
                                                         version))
        bump_version = False  # Did we sign at least one file?
        for file_obj in to_sign:
            if not os.path.exists(file_obj.file_path):
                log.info('File {0} does not exist, skip'.format(file_obj.pk))
                continue
            # Save the original file, before bumping the version.
            backup_path = '{0}.backup_signature'.format(file_obj.file_path)
            shutil.copy(file_obj.file_path, backup_path)
            try:
                # Need to bump the version (modify install.rdf or package.json)
                # before the file is signed.
                bump_version_number(file_obj)
                signed = bool(sign_file(file_obj))
                if signed:  # Bump the version number if at least one signed.
                    bump_version = True
                else:  # We didn't sign, so revert the version bump.
                    shutil.move(backup_path, file_obj.file_path)
            except:
                log.error('Failed signing file {0}'.format(file_obj.pk),
                          exc_info=True)
                # Revert the version bump, restore the backup.
                shutil.move(backup_path, file_obj.file_path)
        # Now update the Version model, if we signed at least one file.
        if bump_version:
            version.update(version=_dot_one(version.version))


def bump_version_number(file_obj):
    """Add a '.1-signed' to the version number."""
    # Create a new xpi with the bumped version.
    bumped = '{0}.bumped'.format(file_obj.file_path)
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
    return '{0}.1-signed'.format(version)


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
