import logging
import urlparse
import random

from django.conf import settings
from locust import TaskSet, task
import lxml.html
from fxa import oauth as fxa_oauth

import helpers

log = logging.getLogger(__name__)

MAX_UPLOAD_POLL_ATTEMPTS = 200
FXA_CONFIG = settings.FXA_CONFIG[settings.DEFAULT_FXA_CONFIG_NAME]


class BaseUserTaskSet(TaskSet):

    def on_start(self):
        self.fxa_account, self.email_account = helpers.get_fxa_account()

        log.info(
            'Created {account} for load-tests'
            .format(account=self.fxa_account))

    def on_stop(self):
        log.info(
            'Cleaning up and destroying {account}'
            .format(account=self.fxa_account))
        helpers.destroy_fxa_account(self.fxa_account, self.email_account)

    def login(self, fxa_account):
        log.debug('calling login/start to generate fxa_state')
        response = self.client.get(
            '/api/v3/accounts/login/start/',
            allow_redirects=True)

        params = dict(urlparse.parse_qsl(response.url))
        fxa_state = params['state']

        log.debug('Get browser id session token')
        fxa_session = helpers.get_fxa_client().login(
            email=fxa_account.email,
            password=fxa_account.password)

        oauth_client = fxa_oauth.Client(
            client_id=FXA_CONFIG['client_id'],
            client_secret=FXA_CONFIG['client_secret'],
            server_url=FXA_CONFIG['oauth_host'])

        log.debug('convert browser id session token into oauth code')
        oauth_code = oauth_client.authorize_code(fxa_session, scope='profile')

        # Now authenticate the user, this will verify the user on the server
        response = self.client.get(
            '/api/v3/accounts/authenticate/',
            params={
                'state': fxa_state,
                'code': oauth_code,
            },
            name='/api/v3/accounts/authenticate/?state=:state'
        )

    def logout(self, account):
        log.debug('Logging out {}'.format(account))
        self.client.get('/en-US/firefox/users/logout/')


class UserTaskSet(BaseUserTaskSet):
    @task(8)
    def browse(self):
        self.client.get('/en-US/firefox/')

        response = self.client.get(
            '/en-US/firefox/extensions/',
            allow_redirects=False, catch_response=True)

        if response.status_code == 200:
            html = lxml.html.fromstring(response.content)
            addon_links = html.cssselect('a.SearchResult-link')
            url = random.choice(addon_links).get('href')
            self.client.get(
                url,
                name='/en-US/firefox/addon/:slug')
        else:
            response.failure('Unexpected status code {}'.format(
                response.status_code))

    @task(10)
    def search(self):
        term = ('Spam', 'Privacy', 'Download')
        self.client.get('/en-US/firefox/search/?platform=linux&q={}'.format(
            random.choice(term)))

    @task(6)
    def browse_and_download_addon(self):
        response = self.client.get(
            '/en-US/firefox/extensions/',
            allow_redirects=False, catch_response=True)

        if response.status_code == 200:
            html = lxml.html.fromstring(response.content)
            download_links = html.cssselect('a.SearchResult-link')
            url = random.choice(download_links).get('href')
            self.client.get(
                url,
                name='/en-US/firefox/downloads/:file_id/')
        else:
            response.failure('Unexpected status code {}'.format(
                response.status_code))

    @task(5)
    def browse_collections(self):
        response = self.client.get(
            '/en-US/firefox/',
            allow_redirects=False, catch_response=True)

        if response.status_code == 200:
            html = lxml.html.fromstring(response.content)
            collection_links = html.cssselect('a.Home-SubjectShelf-link')
            url = random.choice(collection_links).get('href')
            self.client.get(url)
        else:
            response.failure('Unexpected status code {}'.format(
                response.status_code))

    @task(4)
    def browse_categories(self):
        response = self.client.get(
            '/en-US/firefox/extensions/',
            allow_redirects=False, catch_response=True)

        if response.status_code == 200:
            html = lxml.html.fromstring(response.content)
            categories_links = html.cssselect('a.Categories-link')
            url = random.choice(categories_links).get('href')
            self.client.get(url)
        else:
            response.failure('Unexpected status code {}'.format(
                response.status_code))
