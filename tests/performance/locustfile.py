import logging
import os
import sys
import time
import urlparse
import random

# due to locust sys.path manipulation, we need to re-add the project root.
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Now we can load django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
import olympia  # noqa
from django.conf import settings  # noqa
from olympia.amo.urlresolvers import reverse

from locust import HttpLocust, TaskSet, task  # noqa
import lxml.html  # noqa
from lxml.html import submit_form  # noqa
from fxa import oauth as fxa_oauth  # noqa

from . import helpers  # noqa

logging.Formatter.converter = time.gmtime

log = logging.getLogger(__name__)
helpers.install_event_markers()

MAX_UPLOAD_POLL_ATTEMPTS = 200
FXA_CONFIG = settings.FXA_CONFIG[settings.DEFAULT_FXA_CONFIG_NAME]


class UserBehavior(TaskSet):

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

    def submit_form(self, form=None, url=None, extra_values=None):
        if form is None:
            raise ValueError('form cannot be None; url={}'.format(url))

        def submit(method, form_action_url, values):
            values = dict(values)
            if 'csrfmiddlewaretoken' not in values:
                raise ValueError(
                    'Possibly the wrong form. Could not find '
                    'csrfmiddlewaretoken: {}'.format(repr(values)))

            response = self.client.post(
                url or form_action_url, values,
                allow_redirects=False, catch_response=True)

            if response.status_code not in (301, 302):
                # This probably means the form failed and is displaying
                # errors.
                response.failure(
                    'Form submission did not redirect; status={}'
                    .format(response.status_code))

        return submit_form(form, open_http=submit, extra_values=extra_values)

    def login(self, account):
        log.debug('creating fxa account')
        fxa_account, email_account = helpers.get_fxa_account()

        log.debug('calling login/start to generate fxa_state')
        response = self.client.get(
            reverse('accounts.login_start'),
            allow_redirects=False)

        params = dict(urlparse.parse_qsl(response.headers['Location']))
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

        # Now authenticate the user, this will verify the user on the
        response = self.client.get(
            reverse('accounts.authenticate'),
            params={
                'state': fxa_state,
                'code': oauth_code,
            }
        )

    def logout(self, account):
        log.debug('Logging out {}'.format(account))
        self.client.get(reverse('users.logout'))

    def load_upload_form(self):
        url = helpers.submit_url('upload-unlisted')
        response = self.client.get(
            url, allow_redirects=False, catch_response=True)

        if response.status_code == 200:
            html = lxml.html.fromstring(response.content)
            return html.get_element_by_id('create-addon')
        else:
            more_info = ''
            if response.status_code in (301, 302):
                more_info = ('Location: {}'
                             .format(response.headers['Location']))
            response.failure('Unexpected status: {}; {}'
                             .format(response.status_code, more_info))

    def upload_addon(self, form):
        url = helpers.submit_url('upload-unlisted')
        csrfmiddlewaretoken = form.fields['csrfmiddlewaretoken']

        with helpers.get_xpi() as addon_file:
            response = self.client.post(
                reverse('devhub.upload'),
                {'csrfmiddlewaretoken': csrfmiddlewaretoken},
                files={'upload': addon_file},
                name='devhub.upload {}'.format(
                    os.path.basename(addon_file.name)),
                allow_redirects=False,
                catch_response=True)

            if response.status_code == 302:
                poll_url = response.headers['location']
                upload_uuid = self.poll_upload_until_ready(poll_url)
                if upload_uuid:
                    form.fields['upload'] = upload_uuid
                    self.submit_form(form=form, url=url)
            else:
                response.failure('Unexpected status: {}'.format(
                    response.status_code))

    @task(1)
    def upload(self):
        self.login(self.fxa_account)

        form = self.load_upload_form()
        if form:
            self.upload_addon(form)

        self.logout(self.fxa_account)

    @task(5)
    def browse(self):
        self.client.get(reverse('home'))

        response = self.client.get(
            reverse('browse.extensions'),
            allow_redirects=False, catch_response=True)

        if response.status_code == 200:
            html = lxml.html.fromstring(response.content)
            addon_links = html.cssselect('.item.addon h3 a')
            url = random.choice(addon_links).get('href')
            self.client.get(
                url,
                name=reverse('addons.detail', kwargs={'addon_id': ':slug'}))
        else:
            response.failure('Unexpected status code {}'.format(
                response.status_code))

    def poll_upload_until_ready(self, url):
        for i in xrange(MAX_UPLOAD_POLL_ATTEMPTS):
            response = self.client.get(
                url, allow_redirects=False,
                name=reverse('devhub.upload_detail', args=(':uuid',)),
                catch_response=True)

            try:
                data = response.json()
            except ValueError:
                return response.failure(
                    'Failed to parse JSON when polling. '
                    'Status: {} content: {}'.format(
                        response.status_code, response.content))

            if response.status_code == 200:
                if data['error']:
                    return response.failure('Unexpected error: {}'.format(
                        data['error']))
                elif data['validation']:
                    return data['upload']
            else:
                return response.failure('Unexpected status: {}'.format(
                    response.status_code))
            time.sleep(1)
        else:
            response.failure('Upload did not complete in {} tries'.format(
                MAX_UPLOAD_POLL_ATTEMPTS))


class WebsiteUser(HttpLocust):
    task_set = UserBehavior
    min_wait = 5000
    max_wait = 9000
