import logging
from optparse import make_option
import os
import pprint
import re
import shutil
import subprocess
import tempfile

from django.core.management.base import BaseCommand
from django.db import transaction

import path

import amo
import amo.utils
from amo.utils import rm_local_tmp_dir
from files.models import nfd_str
from files.utils import extract_xpi, RDF
from versions.models import Version


log = logging.getLogger('z.migrations')
old_version = re.compile(r'\.1$')


def _log(msg):
    # Sigh. Vanishing log messages.  No really.
    print msg
    log.info(msg)


class Command(BaseCommand):
    help = ("One time script to fix broken jetpack XPIs. See bug 692524 "
            "and bug 693429")
    option_list = BaseCommand.option_list + (
        make_option('--dev', action='store_true',
                    dest='dev', help='Runs against dev versions.'),
    )

    @transaction.commit_manually
    def handle(self, *args, **options):
        success, fails, skipped = 0, 0, 0
        failed_ver_ids = []
        if options.get('dev'):
            _log('using dev IDs')
            ids = DEV_VERSION_IDS
        else:
            _log('using production IDs')
            ids = VERSION_IDS
        for version in Version.uncached.filter(pk__in=ids):
            try:
                if not old_version.search(version.version):
                    _log('skipped: Unexpected version: %s [%s]'
                         % (version.version, version.pk))
                    transaction.rollback()
                    skipped += 1
                    continue
                # eg. 1.0.1 -> 1.0.2
                new_ver_str = old_version.sub('.2', version.version)
                _log('version: %s [%s] -> %s' % (version, version.pk,
                                                 new_ver_str))
                version.version = new_ver_str
                version.version_int = None  # recalculate on save
                version.save()
                for file_ in version.files.all():
                    tmp = tempfile.mkdtemp()
                    try:
                        xpi_dir = os.path.join(tmp, 'xpi_dir')
                        os.mkdir(xpi_dir)
                        extract_xpi(file_.file_path, xpi_dir)
                        xpi = os.path.join(tmp, 'xpi.zip')
                        new_xpi = fix_xpi(xpi, xpi_dir, new_ver_str)
                        replace_xpi(file_, new_xpi, version)
                    finally:
                        rm_local_tmp_dir(tmp)
            except:
                failed_ver_ids.append(version.pk)
                transaction.rollback()
                log.exception(' ** rollback()')
                fails += 1
            else:
                transaction.commit()
                success += 1

        _log('These versions failed: %s' % pprint.pformat(failed_ver_ids))
        _log('SUCCESS: %s' % success)
        _log('FAILS: %s' % fails)
        _log('SKIPPED: %s' % skipped)
        _log('TOTAL: %s' % (success + fails + skipped))


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
    # Replace install.rdf:
    with open(os.path.join(xpi_dir, 'install.rdf'), 'w') as f:
        f.write(str(data))

    wd = os.getcwd()
    try:
        os.chdir(xpi_dir)
        subprocess.check_call(['zip', '-qr', xpi] + os.listdir(os.getcwd()))
    finally:
        os.chdir(wd)
    return path.path(xpi)


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
        if os.path.exists(file_dest):
            backup_file(file_dest)
        new_xpi.copyfile(file_dest)
        _log('file: %s [%s] at %s -> %s at %s' % (old_filename,
                                                  file_.pk, old_filepath,
                                                  file_.filename,
                                                  file_dest))


def backup_file(file_path, base=None, tries=1):
    if not base:
        base = '%s.bak' % file_path
    if tries > 1:
        new_path = '%s.%s' % (base, tries)
    else:
        new_path = base
    if os.path.exists(new_path):
        return backup_file(file_path, base=base, tries=tries + 1)
    _log('backed up: %s -> %s' % (file_path, new_path))
    shutil.copy(file_path, new_path)


# The exact versions to fix:
VERSION_IDS = [1272303, 1271533, 1271532, 1271531, 1271530, 1271527, 1271526,
1271525, 1271523, 1271524, 1271520, 1271519, 1271518, 1271515, 1271514,
1271513, 1271511, 1271500, 1271499, 1271498, 1271497, 1271494, 1271493,
1271479, 1271436, 1271435, 1271434, 1271433, 1271432, 1271431, 1271430,
1271429, 1271428, 1271427, 1271426, 1271425, 1271424, 1271422, 1271421,
1271420, 1271419, 1271418, 1271417, 1271416, 1271414, 1271413, 1271412,
1271411, 1271410, 1271409, 1271408, 1271407, 1271406, 1271403, 1271404,
1271405, 1271402, 1271401, 1271400, 1271399, 1271398, 1271397, 1271396,
1271393, 1271394, 1271392, 1271391, 1271390, 1271389, 1271388, 1271387,
1271386, 1271385, 1271384, 1271382, 1271383, 1271381, 1271378, 1271379,
1271380, 1271377, 1271376, 1271375, 1271374, 1271373, 1271372, 1271371,
1271370, 1271369, 1271368, 1271367, 1271366, 1271365, 1271364, 1271363,
1271361, 1271360, 1271359, 1271356, 1271357, 1271358, 1271355, 1271354,
1271353, 1271352, 1271351, 1271350, 1271349, 1271348, 1271347, 1271345,
1271344, 1271346, 1271342, 1271341, 1271340, 1271337, 1271338, 1271339,
1271336, 1271335, 1271334, 1271331, 1271332, 1271333, 1271330, 1271329,
1271328, 1271327, 1271326, 1271325, 1271324, 1271323, 1271322, 1271320,
1271318, 1271319, 1271317, 1271316, 1271315, 1271314, 1271313, 1271312,
1271311, 1271309, 1271310, 1271308, 1271307, 1271306, 1271305, 1271304,
1271303, 1271302, 1271300, 1271301, 1271299, 1271297, 1271296, 1271295,
1271294, 1271293, 1271292, 1271291, 1271290, 1271289, 1271288, 1271287,
1271286, 1271285, 1271283]

DEV_VERSION_IDS = [1270479, 1270478, 1270481, 1270480, 1270482, 1270483,
1270484, 1270486, 1270487, 1270488, 1270489, 1270490, 1270491, 1270492,
1270493, 1270494, 1270496, 1270495, 1270498, 1270497, 1270500, 1270501,
1270502, 1270503, 1270504, 1270505, 1270506, 1270507, 1270508, 1270509,
1270510, 1270511, 1270512, 1270513, 1270514, 1270515, 1270516, 1270517,
1270519, 1270520, 1270521, 1270522, 1270523, 1270524, 1270525, 1270526,
1270527, 1270528, 1270529, 1270530, 1270531, 1270532, 1270533, 1270534,
1270536, 1270537, 1270539, 1270540, 1270541, 1270542, 1270543, 1270544,
1270545, 1270546, 1270547, 1270548, 1270549, 1270550, 1270551, 1270552,
1270553, 1270554, 1270555, 1270556, 1270557, 1270558, 1270559, 1270560,
1270562, 1270561, 1270564, 1270565, 1270566, 1270567, 1270568, 1270569,
1270572, 1270573, 1270574, 1270575, 1270576, 1270577, 1270578, 1270579,
1270580, 1270582, 1270583, 1270584, 1270585, 1270586, 1270587, 1270589,
1270590, 1270591, 1270592, 1270593, 1270594, 1270597, 1270599, 1270600,
1270601, 1270602, 1270603, 1270633, 1270634, 1270635, 1270636, 1270637,
1270639, 1270640]
