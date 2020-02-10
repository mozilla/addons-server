import bsdiff4
import json
import os
import random

from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia.addons.models import Addon
from olympia.blocklist.models import Block
from olympia.blocklist.utils import generateMLBF
from olympia.files.models import File


log = olympia.core.logger.getLogger('z.amo.blocklist')


class Command(BaseCommand):
    help = ('Export AMO blocklist to filter cascade blob')

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--capacity',
            type=float,
            default='1.1',
            dest='capacity',
            help='MLBF capacity.')
        parser.add_argument(
            'id',
            help="CT baseline identifier",
            metavar=('ID'))
        parser.add_argument(
            '--previous-id',
            help="Previous identifier to use for diff",
            metavar=('DIFFID'),
            default=None)
        parser.add_argument(
            '--addon-guids-input',
            help='Path to json file with [[guid, version],...] data for all '
                 'addons. If not provided will be generated from '
                 'Addons&Versions in the database',
            default=None)
        parser.add_argument(
            '--block-guids-input',
            help='Path to json file with [[guid, version],...] data for '
                 'Blocks.  If not provided will be generated from Blocks in '
                 'the database',
            default=None)

    def get_blocked_guids(self):
        blocks = Block.objects.all()
        blocks_guids = [block.guid for block in blocks]
        addons_dict = Addon.unfiltered.in_bulk(blocks_guids, field_name='guid')
        for block in blocks:
            block.addon = addons_dict.get(block.guid)
        Block.preload_addon_versions(blocks)
        all_versions = {}
        # First collect all the blocked versions
        for block in blocks:
            is_all_versions = (
                block.min_version == Block.MIN and
                block.max_version == Block.MAX)
            versions = {
                version_id: (block.guid, version)
                for version, (version_id, _) in block.addon_versions.items()
                if is_all_versions or block.is_version_blocked(version)}
            all_versions.update(versions)
        # Now we need the cert_ids
        cert_nums = File.objects.filter(
            version_id__in=all_versions.keys()).values_list(
                'version_id', 'cert_serial_num')
        return [
            (all_versions[version_id][0], all_versions[version_id][1], cert_nm)
            for version_id, cert_nm in cert_nums]

    def get_all_guids(self):
        return File.objects.values_list(
            'version__addon__guid', 'version__version', 'cert_serial_num')

    def load_json(self, json_path):
        def tuplify(record):
            return tuple(
                record if len(record) == 3 else
                record + [str(random.randint(100000, 999999))])

        with open(json_path) as json_file:
            data = json.load(json_file)
        return [tuplify(record) for record in data]

    def save_blocklist(self, stats, mlbf, id_, previous_id=None):
        out_file = os.path.join(settings.TMP_PATH, 'mlbf', id_, 'filter')
        meta_file = os.path.join(settings.TMP_PATH, 'mlbf', id_, 'filter.meta')

        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        with default_storage.open(out_file, 'wb') as mlbf_file:
            log.info("Writing to file {}".format(out_file))
            mlbf.tofile(mlbf_file)
        stats['mlbf_filesize'] = os.stat(out_file).st_size

        with default_storage.open(meta_file, 'wb') as mlbf_meta_file:
            log.info("Writing to meta file {}".format(meta_file))
            mlbf.saveDiffMeta(mlbf_meta_file)
        stats['mlbf_metafilesize'] = os.stat(meta_file).st_size

        if previous_id:
            diff_base_file = os.path.join(
                settings.TMP_PATH, 'mlbf', str(previous_id), 'filter')
            patch_file = os.path.join(
                settings.TMP_PATH, 'mlbf', id_, 'filter.patch')
            log.info(
                "Generating patch file {patch} from {base} to {out}".format(
                    patch=patch_file, base=diff_base_file,
                    out=out_file))
            bsdiff4.file_diff(
                diff_base_file, out_file, patch_file)
            stats['mlbf_diffsize'] = os.stat(patch_file).st_size

    def handle(self, *args, **options):
        log.debug('Exporting blocklist to file')
        stats = {}
        blocked_guids = (
            self.load_json(options.get('block_guids_input'))
            if options.get('block_guids_input') else
            self.get_blocked_guids())
        all_guids = (
            self.load_json(options.get('addon_guids_input'))
            if options.get('addon_guids_input') else
            self.get_all_guids())
        not_blocked_guids = list(set(all_guids) - set(blocked_guids))
        stats['mlbf_blocked_count'] = len(blocked_guids)
        stats['mlbf_unblocked_count'] = len(not_blocked_guids)

        mlbf = generateMLBF(
            stats,
            blocked=blocked_guids,
            not_blocked=not_blocked_guids,
            capacity=options.get('capacity'),
            diffMetaFile=None)
        mlbf.check(entries=blocked_guids, exclusions=not_blocked_guids)
        self.save_blocklist(
            stats,
            mlbf,
            options.get('id'),
            options.get('previous_id'))
        print(stats)
