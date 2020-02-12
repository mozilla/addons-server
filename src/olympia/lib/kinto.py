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
    _setup_done = False
    _needs_signoff = False

    def __init__(self, bucket, collection):
        self.username = settings.BLOCKLIST_KINTO_USERNAME
        self.password = settings.BLOCKLIST_KINTO_PASSWORD
        self.bucket = bucket
        self.collection = collection

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
        host = settings.KINTO_API_URL
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
        # check if the bucket and collection exist
        host = settings.KINTO_API_URL
        url = (
            f'{host}buckets/{self.bucket}/'
            f'collections/{self.collection}/records')
        headers = self.headers
        response = requests.get(url, headers=headers)
        if response.status_code == 403:
            # lets create them
            data = {'permissions': {'read': ["system.Everyone"]}}
            log.info(
                'Creating kinto bucket %s and collection %s' %
                (self.bucket, self.collection))
            response = requests.put(
                f'{host}buckets/{self.bucket}',
                json=data,
                headers=headers)
            response = requests.put(
                f'{host}buckets/{self.bucket}/collections/{self.collection}',
                json=data,
                headers=headers)

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
            f'{settings.KINTO_API_URL}buckets/{self.bucket}/'
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
        self._needs_signoff = True
        return response.json().get('data', {})

    def delete_record(self, kinto_id):
        self.setup()
        url = (
            f'{settings.KINTO_API_URL}buckets/{self.bucket}/'
            f'collections/{self.collection}/records/{kinto_id}')
        requests.delete(
            url, headers=self.headers)
        self._needs_signoff = True

    def signoff_request(self):
        if not self._needs_signoff:
            return
        self.setup()
        url = (
            f'{settings.KINTO_API_URL}buckets/{self.bucket}/'
            f'collections/{self.collection}')
        requests.patch(
            url, json={'data': {'status': 'to-review'}}, headers=self.headers)
        self._needs_signoff = False
