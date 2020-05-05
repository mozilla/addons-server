import json
import uuid
from base64 import b64encode

from django.conf import settings

import requests

import olympia.core.logger


log = olympia.core.logger.getLogger('lib.kinto')


class KintoServer(object):
    username = None
    password = None
    bucket = None
    collection = None
    kinto_sign_off_needed = True
    _setup_done = False
    _changes = False

    def __init__(self, bucket, collection, kinto_sign_off_needed=True):
        self.username = settings.BLOCKLIST_KINTO_USERNAME
        self.password = settings.BLOCKLIST_KINTO_PASSWORD
        self.bucket = bucket
        self.collection = collection
        self.kinto_sign_off_needed = kinto_sign_off_needed

    def setup(self):
        if self._setup_done:
            return
        if settings.KINTO_API_IS_TEST_SERVER:
            self.setup_test_server_auth()
            self.bucket = f'{self.bucket}_{self.username}'
            self.setup_test_server_collection()
        self._setup_done = True

    @property
    def headers(self):
        b64 = b64encode(f'{self.username}:{self.password}'.encode()).decode()
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Basic {b64}'}

    def setup_test_server_auth(self):
        # check if the user already exists in kinto's accounts
        host = settings.REMOTE_SETTINGS_WRITER_URL
        response = requests.get(host, headers=self.headers)
        user_id = response.json().get('user', {}).get('id')
        if user_id != f'account:{self.username}':
            # lets create it
            log.info('Creating kinto test account for %s' % self.username)
            response = requests.put(
                f'{host}accounts/{self.username}',
                json={'data': {'password': self.password}},
                headers={'Content-Type': 'application/json'})
            if response.status_code != 201:
                log.error(
                    'Creating kinto test account for %s failed. [%s]' %
                    (self.username, response.content),
                    stack_info=True)
                raise ConnectionError('Kinto account not created')

    def setup_test_server_collection(self):
        # check if the bucket exists
        bucket_url = (
            f'{settings.REMOTE_SETTINGS_WRITER_URL}buckets/{self.bucket}')
        headers = self.headers
        response = requests.get(bucket_url, headers=headers)
        data = {'permissions': {'read': ["system.Everyone"]}}
        if response.status_code == 403:
            # lets create them
            log.info(
                'Creating kinto bucket %s and collection %s' %
                (self.bucket, self.collection))
            response = requests.put(bucket_url, json=data, headers=headers)
        # and the collection
        collection_url = f'{bucket_url}/collections/{self.collection}'
        response = requests.get(collection_url, headers=headers)
        if response.status_code == 404:
            response = requests.put(collection_url, json=data, headers=headers)
            if response.status_code != 201:
                log.error(
                    'Creating collection %s/%s failed: %s' %
                    (self.bucket, self.collection, response.content),
                    stack_info=True)
                raise ConnectionError('Kinto collection not created')

    def publish_record(self, data, kinto_id=None):
        """Publish a record to kinto.  If `kinto_id` is not None the existing
        record will be updated (PUT); otherwise a new record will be created
        (POST)."""
        self.setup()

        add_url = (
            f'{settings.REMOTE_SETTINGS_WRITER_URL}buckets/{self.bucket}/'
            f'collections/{self.collection}/records')
        json_data = {'data': data}
        if not kinto_id:
            log.info('Creating record for [%s]' % data.get('guid'))
            response = requests.post(
                add_url, json=json_data, headers=self.headers)
        else:
            log.info(
                'Updating record [%s] for [%s]' % (kinto_id, data.get('guid')))
            update_url = f'{add_url}/{kinto_id}'
            response = requests.put(
                update_url, json=json_data, headers=self.headers)
        if response.status_code not in (200, 201):
            log.error(
                'Creating record for [%s] failed: %s' %
                (data.get('guid'), response.content),
                stack_info=True)
            raise ConnectionError('Kinto record not created/updated')
        self._changes = True
        return response.json().get('data', {})

    def publish_attachment(self, data, attachment, kinto_id=None):
        """Publish an attachment to a record on kinto.  If `kinto_id` is not
        None the existing record will be updated; otherwise a new record will
        be created.
        `attachment` is a tuple of (filename, file object, content type)"""
        self.setup()

        if not kinto_id:
            log.info('Creating record')
        else:
            log.info(
                'Updating record [%s]' % kinto_id)

        headers = self.headers
        del headers['Content-Type']
        json_data = {'data': json.dumps(data)}
        kinto_id = kinto_id or uuid.uuid4()
        attach_url = (
            f'{settings.REMOTE_SETTINGS_WRITER_URL}buckets/{self.bucket}/'
            f'collections/{self.collection}/records/{kinto_id}/attachment')
        files = [('attachment', attachment)]
        response = requests.post(
            attach_url,
            data=json_data,
            headers=headers,
            files=files)
        if response.status_code not in (200, 201):
            log.error(
                'Creating record for [%s] failed: %s' %
                (kinto_id, response.content),
                stack_info=True)
            raise ConnectionError('Kinto record not created/updated')
        self._changes = True
        return response.json().get('data', {})

    def delete_record(self, kinto_id):
        self.setup()
        url = (
            f'{settings.REMOTE_SETTINGS_WRITER_URL}buckets/{self.bucket}/'
            f'collections/{self.collection}/records/{kinto_id}')
        requests.delete(
            url, headers=self.headers)
        self._changes = True

    def delete_all_records(self):
        self.setup()
        url = (
            f'{settings.REMOTE_SETTINGS_WRITER_URL}buckets/{self.bucket}/'
            f'collections/{self.collection}/records')
        requests.delete(url, headers=self.headers)
        self._changes = True

    def complete_session(self):
        if not self._changes:
            return
        self.setup()
        url = (
            f'{settings.REMOTE_SETTINGS_WRITER_URL}buckets/{self.bucket}/'
            f'collections/{self.collection}')
        status = 'to-review' if self.kinto_sign_off_needed else 'to-sign'
        requests.patch(
            url, json={'data': {'status': status}}, headers=self.headers)
        self._changes = False
