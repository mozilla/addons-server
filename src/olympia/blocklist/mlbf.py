import json
import os
import secrets
from collections import defaultdict

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.utils.functional import cached_property

from filtercascade import FilterCascade
from filtercascade.fileformats import HashAlgorithm

import olympia.core.logger
from olympia.constants.blocklist import BASE_REPLACE_THRESHOLD


log = olympia.core.logger.getLogger('z.amo.blocklist')


class MLBF():
    KEY_FORMAT = '{guid}:{version}'

    def __init__(self, id_):
        # simplify later code by assuming always a string
        self.id = str(id_)

    @classmethod
    def fetch_blocked_from_db(cls):
        from olympia.files.models import File
        from olympia.blocklist.models import Block

        blocks = Block.objects.all()
        blocks_guids = [block.guid for block in blocks]

        file_qs = File.objects.filter(
            version__addon__addonguid__guid__in=blocks_guids,
            is_signed=True,
            is_webextension=True,
        ).order_by('version_id').values(
            'version__addon__addonguid__guid',
            'version__version',
            'version_id')
        addons_versions = defaultdict(list)
        for file_ in file_qs:
            addon_key = file_['version__addon__addonguid__guid']
            addons_versions[addon_key].append(
                (file_['version__version'], file_['version_id']))

        all_versions = {}
        # collect all the blocked versions
        for block in blocks:
            is_all_versions = (
                block.min_version == Block.MIN and
                block.max_version == Block.MAX)
            versions = {
                version_id: (block.guid, version)
                for version, version_id in addons_versions[block.guid]
                if is_all_versions or block.is_version_blocked(version)}
            all_versions.update(versions)
        return all_versions

    @classmethod
    def fetch_all_versions_from_db(cls, excluding_version_ids=None):
        from olympia.versions.models import Version

        qs = (
            Version.unfiltered.exclude(id__in=excluding_version_ids or ())
                   .values_list('addon__addonguid__guid', 'version'))

        return list(qs)

    @classmethod
    def hash_filter_inputs(cls, input_list):
        """Returns a set"""
        return {
            cls.KEY_FORMAT.format(guid=guid, version=version)
            for (guid, version) in input_list}

    @classmethod
    def generate_mlbf(cls, stats, blocked, not_blocked):
        log.info('Starting to generating bloomfilter')

        cascade = FilterCascade(
            defaultHashAlg=HashAlgorithm.SHA256,
            salt=secrets.token_bytes(16),
        )

        error_rates = sorted((len(blocked), len(not_blocked)))
        cascade.set_crlite_error_rates(
            include_len=error_rates[0], exclude_len=error_rates[1])

        stats['mlbf_blocked_count'] = len(blocked)
        stats['mlbf_notblocked_count'] = len(not_blocked)

        cascade.initialize(include=blocked, exclude=not_blocked)

        stats['mlbf_version'] = cascade.version
        stats['mlbf_layers'] = cascade.layerCount()
        stats['mlbf_bits'] = cascade.bitCount()

        log.info(
            f'Filter cascade layers: {cascade.layerCount()}, '
            f'bit: {cascade.bitCount()}')

        cascade.verify(include=blocked, exclude=not_blocked)
        return cascade

    @property
    def filter_path(self):
        return os.path.join(
            settings.MLBF_STORAGE_PATH, self.id, 'filter')

    @property
    def _blocked_path(self):
        return os.path.join(
            settings.MLBF_STORAGE_PATH, self.id, 'blocked.json')

    @cached_property
    def blocked_json(self):
        with storage.open(self._blocked_path, 'r') as json_file:
            return json.load(json_file)

    def fetch_blocked_json(self):
        """A safer version of .blocked_json that will generate from the db
        if the cached_property isn't set."""
        try:
            return self.blocked_json
        except FileNotFoundError:
            # when self._blocked_path doesn't exist
            pass
        blocked_ids_to_versions = self.fetch_blocked_from_db()
        blocked = blocked_ids_to_versions.values()
        # cache version ids so query in fetch_not_blocked_json is efficient
        self._version_excludes = blocked_ids_to_versions.keys()
        self.blocked_json = list(self.hash_filter_inputs(blocked))
        return self.blocked_json

    @property
    def _not_blocked_path(self):
        return os.path.join(
            settings.MLBF_STORAGE_PATH, self.id, 'notblocked.json')

    @cached_property
    def not_blocked_json(self):
        with storage.open(self._not_blocked_path, 'r') as json_file:
            return json.load(json_file)

    def fetch_not_blocked_json(self):
        """A safer version of .not_blocked_json that will generate from the db
        if the cached_property isn't set."""
        try:
            return self.not_blocked_json
        except FileNotFoundError:
            # when self._not_blocked_path doesn't exist
            pass
        # see fetch_blocked_json
        version_excludes = getattr(
            self, '_version_excludes', self.fetch_blocked_from_db().keys())
        # even though we exclude all the version ids in the query there's an
        # edge case where the version string occurs twice for an addon so we
        # ensure not_blocked_json doesn't contain any blocked_json.
        self.not_blocked_json = list(
            self.hash_filter_inputs(
                self.fetch_all_versions_from_db(version_excludes)) -
            set(self.blocked_json))

        return self.not_blocked_json

    @property
    def _stash_path(self):
        return os.path.join(
            settings.MLBF_STORAGE_PATH, self.id, 'stash.json')

    @cached_property
    def stash_json(self):
        with storage.open(self._stash_path, 'r') as json_file:
            return json.load(json_file)

    def generate_and_write_mlbf(self):
        stats = {}

        blocked_json = self.fetch_blocked_json()
        not_blocked_json = self.fetch_not_blocked_json()

        # write blocked json
        blocked_path = self._blocked_path
        with storage.open(blocked_path, 'w') as json_file:
            log.info("Writing to file {}".format(blocked_path))
            json.dump(blocked_json, json_file)
        # and the not blocked json
        not_blocked_path = self._not_blocked_path
        with storage.open(not_blocked_path, 'w') as json_file:
            log.info("Writing to file {}".format(not_blocked_path))
            json.dump(not_blocked_json, json_file)

        bloomfilter = self.generate_mlbf(
            stats=stats,
            blocked=blocked_json,
            not_blocked=not_blocked_json)

        # write bloomfilter
        mlbf_path = self.filter_path
        with storage.open(mlbf_path, 'wb') as filter_file:
            log.info("Writing to file {}".format(mlbf_path))
            bloomfilter.tofile(filter_file)
            stats['mlbf_filesize'] = os.stat(mlbf_path).st_size

        log.info(json.dumps(stats))

    @classmethod
    def generate_diffs(cls, previous, current):
        previous = set(previous)
        current = set(current)
        extras = current - previous
        deletes = previous - current
        return extras, deletes

    def write_stash(self, previous_mlbf):
        # compare previous with current blocks
        extras, deletes = self.generate_diffs(
            previous_mlbf.blocked_json, self.blocked_json)
        self.stash_json = {
            'blocked': list(extras),
            'unblocked': list(deletes),
        }
        # write stash
        stash_path = self._stash_path
        with storage.open(stash_path, 'w') as json_file:
            log.info("Writing to file {}".format(stash_path))
            json.dump(self.stash_json, json_file)

    def should_reset_base_filter(self, previous_base_mlbf):
        try:
            # compare base with current blocks
            extras, deletes = self.generate_diffs(
                previous_base_mlbf.blocked_json, self.fetch_blocked_json())
            return (len(extras) + len(deletes)) > BASE_REPLACE_THRESHOLD
        except FileNotFoundError:
            # when previous_base_mlfb._blocked_path doesn't exist
            return True

    def blocks_changed_since_previous(self, previous_base_mlbf):
        try:
            # compare base with current blocks
            extras, deletes = self.generate_diffs(
                previous_base_mlbf.blocked_json, self.fetch_blocked_json())
            return bool(extras) or bool(deletes)
        except FileNotFoundError:
            # when previous_base_mlfb._blocked_path doesn't exist
            return True
