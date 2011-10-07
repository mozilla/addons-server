import logging
import os
import pprint
import shutil
import tempfile

from django.db import transaction

import path

import amo
import amo.utils
from files.models import nfd_str
from files.utils import extract_xpi, RDF, SafeUnzip
from versions.models import Version


log = logging.getLogger('z.migrations')


@transaction.commit_manually
def run():
    success, fails = 0, 0
    failed_ver_ids = []
    for version in Version.objects.filter(version__endswith='sdk.1.1'):
        try:
            new_ver_str = version.version.replace('.sdk.1.1', '.1')
            log.info('%s [%s] -> %s' % (version, version.pk, new_ver_str))
            version.version = new_ver_str
            version.save()
            for file_ in version.files.all():
                tmp = tempfile.mkdtemp()
                try:
                    xpi_dir = os.path.join(tmp, 'xpi_dir')
                    os.mkdir(xpi_dir)
                    xpi = os.path.join(tmp, 'xpi.zip')
                    shutil.copy(file_.file_path, xpi)
                    extract_xpi(file_.file_path, xpi_dir)
                    new_xpi = fix_xpi(xpi, xpi_dir, new_ver_str)
                    replace_xpi(file_, new_xpi, version)
                finally:
                    shutil.rmtree(tmp)
        except:
            failed_ver_ids.append(version.pk)
            transaction.rollback()
            log.exception(' ** rollback()')
            fails += 1
        else:
            transaction.commit()
            success += 1

    log.info('These versions failed: %s' % pprint.pformat(failed_ver_ids))
    summary = ['SUCCESS: ', success, "\n",
               'FAILS: ', fails, "\n",
               'TOTAL: ', (success + fails)]
    log.info(''.join([str(s) for s in summary]))
    print ''.join([str(s) for s in summary])
    print 'Check the log for details'


def fix_xpi(xpi, xpi_dir, new_version):
    with open(os.path.join(xpi_dir, 'install.rdf')) as f:
        data = RDF(f.read())
    parent = (data.dom.documentElement
              .getElementsByTagName('Description')[0])
    for v in parent.getElementsByTagName('em:version'):
        parent.removeChild(v)
        v.unlink()
    elem = data.dom.createElement('em:version')
    elem.appendChild(data.dom.createTextNode(new_version))
    parent.appendChild(elem)
    outzip = SafeUnzip(xpi, mode='w')
    outzip.is_valid()
    outzip.zip.writestr('install.rdf', str(data))
    outzip.zip.close()
    return path.path(amo.utils.smart_path(nfd_str(xpi)))


def replace_xpi(file_, new_xpi, version):
    old_filename = file_.filename
    old_filepath = file_.file_path
    # Now that we have a new version, make a new filename.
    file_.filename = file_.generate_filename(extension='.xpi')
    file_.hash = file_.generate_hash(new_xpi)
    file_.size = int(max(1, round(new_xpi.size / 1024, 0)))  # kB
    file_.save()
    destinations = [path.path(version.path_prefix)]
    if file_.status in amo.MIRROR_STATUSES:
        destinations.append(path.path(version.mirror_path_prefix))
    for dest in destinations:
        if not dest.exists():
            dest.makedirs()
        file_dest = dest / nfd_str(file_.filename)
        new_xpi.copyfile(file_dest)
        log.info('%s [%s] at %s -> %s at %s' % (old_filename,
                                                file_.pk, old_filepath,
                                                file_.filename,
                                                file_dest))
