import json
import uuid
from base64 import b64encode

from django.conf import settings

import requests

import olympia.core.logger


log = olympia.core.logger.getLogger('lib.remote_settings')


class RemoteSettings:
    username = None
    password = None
    bucket = None
    collection = None
    sign_off_needed = True
    _setup_done = False
    _changes = False

    def __init__(self, bucket, collection, sign_off_needed=True):
        self.username = settings.BLOCKLIST_REMOTE_SETTINGS_USERNAME
        self.password = settings.BLOCKLIST_REMOTE_SETTINGS_PASSWORD
        self.bucket = bucket
        self.collection = collection
        self.sign_off_needed = sign_off_needed

    @property
    def headers(self):
        b64 = b64encode(f'{self.username}:{self.password}'.encode()).decode()
        return {'Content-Type': 'application/json', 'Authorization': f'Basic {b64}'}

    def heartbeat(self):
        url = f'{settings.REMOTE_SETTINGS_WRITER_URL}__heartbeat__'
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def authenticated(self):
        # Return True if configured credentials can authenticate.
        response = requests.get(
            settings.REMOTE_SETTINGS_WRITER_URL, headers=self.headers
        )
        return 'id' in response.json().get('user', {})

    def publish_record(self, data, legacy_id=None):
        """Publish a record to remote settings.  If `legacy_id` is not None the
        existing record will be updated (PUT); otherwise a new record will be
        created (POST)."""
        add_url = (
            f'{settings.REMOTE_SETTINGS_WRITER_URL}buckets/{self.bucket}/'
            f'collections/{self.collection}/records'
        )
        json_data = {'data': data}
        if not legacy_id:
            log.info('Creating record for [%s]' % data.get('guid'))
            response = requests.post(add_url, json=json_data, headers=self.headers)
        else:
            log.info(
                'Updating record [{}] for [{}]'.format(legacy_id, data.get('guid'))
            )
            update_url = f'{add_url}/{legacy_id}'
            response = requests.put(update_url, json=json_data, headers=self.headers)
        if response.status_code not in (200, 201):
            log.error(
                'Creating record for [%s] failed: %s'
                % (data.get('guid'), response.content),
                stack_info=True,
            )
            raise ConnectionError('Remote settings record not created/updated')
        self._changes = True
        return response.json().get('data', {})

    def publish_attachment(self, data, attachment, legacy_id=None):
        """Publish an attachment to a record on remote settings. If `legacy_id`
        is not None the existing record will be updated; otherwise a new record
        will be created.
        `attachment` is a tuple of (filename, file object, content type)"""
        if not legacy_id:
            log.info('Creating record')
        else:
            log.info('Updating record [%s]' % legacy_id)

        headers = self.headers
        del headers['Content-Type']
        json_data = {'data': json.dumps(data)}
        legacy_id = legacy_id or uuid.uuid4()
        attach_url = (
            f'{settings.REMOTE_SETTINGS_WRITER_URL}buckets/{self.bucket}/'
            f'collections/{self.collection}/records/{legacy_id}/attachment'
        )
        files = [('attachment', attachment)]
        response = requests.post(
            attach_url, data=json_data, headers=headers, files=files
        )
        if response.status_code not in (200, 201):
            log.error(
                f'Creating record for [{legacy_id}] failed: {response.content}',
                stack_info=True,
            )
            raise ConnectionError('Remote settings record not created/updated')
        self._changes = True
        return response.json().get('data', {})

    def delete_record(self, legacy_id):
        url = (
            f'{settings.REMOTE_SETTINGS_WRITER_URL}buckets/{self.bucket}/'
            f'collections/{self.collection}/records/{legacy_id}'
        )
        requests.delete(url, headers=self.headers)
        self._changes = True

    def delete_all_records(self):
        url = (
            f'{settings.REMOTE_SETTINGS_WRITER_URL}buckets/{self.bucket}/'
            f'collections/{self.collection}/records'
        )
        requests.delete(url, headers=self.headers)
        self._changes = True

    def complete_session(self):
        if not self._changes:
            return
        url = (
            f'{settings.REMOTE_SETTINGS_WRITER_URL}buckets/{self.bucket}/'
            f'collections/{self.collection}'
        )
        status = 'to-review' if self.sign_off_needed else 'to-sign'
        requests.patch(url, json={'data': {'status': status}}, headers=self.headers)
        self._changes = False
