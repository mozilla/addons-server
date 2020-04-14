import json
import math
import os
import secrets
from collections import defaultdict

from django.conf import settings
from django.core.files.storage import default_storage as storage

from filtercascade import FilterCascade
from filtercascade.fileformats import HashAlgorithm

import olympia.core.logger


log = olympia.core.logger.getLogger('z.amo.blocklist')


class MLBF():
    KEY_FORMAT = '{guid}:{version}'

    blocked = []
    not_blocked = []

    def __init__(self, id_):
        # simplify later code by assuming always a string
        self.id = str(id_)

    @classmethod
    def get_blocked_versions(cls):
        from olympia.files.models import File
        from olympia.blocklist.models import Block

        blocks = Block.objects.all()
        blocks_guids = [block.guid for block in blocks]

        file_qs = File.objects.filter(
            version__addon__guid__in=blocks_guids,
            is_signed=True,
            is_webextension=True,
        ).order_by('version_id').values(
            'version__addon__guid',
            'version__version',
            'version_id')
        addons_versions = defaultdict(dict)
        for file_ in file_qs:
            addon_key = file_['version__addon__guid']
            addons_versions[addon_key][file_['version__version']] = (
                file_['version_id'])

        all_versions = {}
        # collect all the blocked versions
        for block in blocks:
            is_all_versions = (
                block.min_version == Block.MIN and
                block.max_version == Block.MAX)
            versions = {
                version_id: (block.guid, version)
                for version, version_id in addons_versions[block.guid].items()
                if is_all_versions or block.is_version_blocked(version)}
            all_versions.update(versions)
        return all_versions

    @classmethod
    def get_all_guids(cls, excluding_version_ids=None):
        from olympia.versions.models import Version

        return (
            Version.unfiltered.exclude(id__in=excluding_version_ids or ())
                   .values_list('addon__guid', 'version'))

    @classmethod
    def hash_filter_inputs(cls, input_list):
        return [
            cls.KEY_FORMAT.format(guid=guid, version=version)
            for (guid, version) in input_list]

    @classmethod
    def generate_mlbf(cls, stats, blocked, not_blocked):
        """Originally based on:
        https://github.com/mozilla/crlite/blob/master/create_filter_cascade/certs_to_crlite.py
        (not so much any longer, apart from the fprs calculation)
        """
        salt = secrets.token_bytes(16)

        stats['mlbf_blocked_count'] = len(blocked)
        stats['mlbf_notblocked_count'] = len(not_blocked)

        fprs = [len(blocked) / (math.sqrt(2) * len(not_blocked)), 0.5]

        log.info("Generating filter")
        cascade = FilterCascade(
            filters=[],
            error_rates=fprs,
            defaultHashAlg=HashAlgorithm.SHA256,
            salt=salt,
        )
        cascade.initialize(include=blocked, exclude=not_blocked)

        stats['mlbf_fprs'] = fprs
        stats['mlbf_version'] = cascade.version
        stats['mlbf_layers'] = cascade.layerCount()
        stats['mlbf_bits'] = cascade.bitCount()

        log.debug("Filter cascade layers: {layers}, bit: {bits}".format(
            layers=cascade.layerCount(), bits=cascade.bitCount()))

        cascade.verify(include=blocked, exclude=not_blocked)
        return cascade

    @property
    def filter_path(self):
        return os.path.join(
            settings.MLBF_STORAGE_PATH, self.id, 'filter')

    @property
    def blocked_path(self):
        return os.path.join(
            settings.MLBF_STORAGE_PATH, self.id, 'blocked.json')

    @property
    def not_blocked_path(self):
        return os.path.join(
            settings.MLBF_STORAGE_PATH, self.id, 'notblocked.json')

    @property
    def stash_path(self):
        return os.path.join(
            settings.MLBF_STORAGE_PATH, self.id, 'stash.json')

    def generate_and_write_mlbf(self, *, blocked=None, not_blocked=None):
        stats = {}

        if not blocked:
            blocked_versions = self.get_blocked_versions()
            blocked = blocked_versions.values()
            version_excludes = blocked_versions.keys()
        else:
            version_excludes = ()

        self.blocked = self.hash_filter_inputs(blocked)
        self.not_blocked = self.hash_filter_inputs(
            not_blocked or self.get_all_guids(version_excludes))

        bloomfilter = self.generate_mlbf(
            stats=stats, blocked=self.blocked, not_blocked=self.not_blocked)
        # write bloomfilter
        mlbf_path = self.filter_path
        with storage.open(mlbf_path, 'wb') as filter_file:
            log.info("Writing to file {}".format(mlbf_path))
            bloomfilter.tofile(filter_file)
            stats['mlbf_filesize'] = os.stat(mlbf_path).st_size
        # write blocked json
        blocked_path = self.blocked_path
        with storage.open(blocked_path, 'w') as json_file:
            log.info("Writing to file {}".format(blocked_path))
            json.dump(self.blocked, json_file)
        # and the not blocked json
        not_blocked_path = self.not_blocked_path
        with storage.open(not_blocked_path, 'w') as json_file:
            log.info("Writing to file {}".format(not_blocked_path))
            json.dump(self.not_blocked, json_file)

        log.info(json.dumps(stats))

    @classmethod
    def generate_diffs(cls, previous, current):
        previous = set(previous)
        current = set(current)
        extras = current - previous
        deletes = previous - current
        return extras, deletes

    def write_stash(self, previous_id):
        # load last mlbf blocked guids
        previous_mlbf = MLBF(previous_id)
        with storage.open(previous_mlbf.blocked_path, 'r') as json_file:
            previous_blocked = json.load(json_file)
        # compare with current blocks
        extras, deletes = self.generate_diffs(
            previous_blocked, self.blocked)
        stash = {
            'blocked': list(extras),
            'unblocked': list(deletes),
        }
        # write stash
        stash_path = self.stash_path
        with storage.open(stash_path, 'w') as json_file:
            log.info("Writing to file {}".format(stash_path))
            json.dump(stash, json_file)
