import json
import logging
import shutil
import zipfile

from celeryutils import task
from lxml import etree

import amo
from versions.models import Version
from lib.crypto.packaged import sign_file, SigningError

# Python 2.6 and earlier doesn't have context manager support
ZipFile = zipfile.ZipFile
if not hasattr(zipfile.ZipFile, "__enter__"):
    class ZipFile(zipfile.ZipFile):
        def __enter__(self):
            return self

        def __exit__(self, type, value, traceback):
            self.close()

log = logging.getLogger('z.task')


@task
def sign_addons(addon_ids, force=False, **kw):
    log.info('[{0}] Signing addons.'.format(addon_ids))
    for version in Version.objects.filter(
            addon_id__in=addon_ids, addon__type=amo.ADDON_EXTENSION):
        # We need to bump the version number of the file and the Version, so
        # the Firefox extension update mecanism picks this new signed version
        # and installs it.
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
        try:
            for file_obj in to_sign:
                bump_version_number(file_obj)
                sign_file(file_obj)
            # Now update the Version model.
            version.update(version='{0}.1'.format(version.version))
        except (SigningError, zipfile.BadZipFile) as e:
            log.warning(
                'Failed signing version {0}: {1}.'.format(version.pk, e))


def bump_version_number(file_obj):
    """Add a .1 to the version number in the install.rdf or package.json."""
    # Create a new xpi with the bumped version.
    bumped = '{0}.bumped'.format(file_obj.file_path)
    # Copy the original XPI, with the updated install.rdf or package.json.
    with ZipFile(file_obj.file_path, 'r') as source:
        file_list = source.infolist()
        with ZipFile(bumped, 'w', zipfile.ZIP_DEFLATED) as dest:
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
    """Returns the version with an appended .1 on it."""
    return '{0}.1'.format(version)


def _bump_version_in_install_rdf(content):
    """Add a '.1' to the version number in the install.rdf provided."""
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
    """Add a '.1' to the version number in the package.json provided."""
    bumped = json.loads(content)
    if 'version' in bumped:
        bumped['version'] = _dot_one(bumped['version'])
    return json.dumps(bumped)
