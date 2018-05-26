import os
import logging

import gevent
from django.conf import settings
from locust import task
import lxml.html
from lxml.html import submit_form

import helpers
from .user import BaseUserTaskSet

log = logging.getLogger(__name__)

MAX_UPLOAD_POLL_ATTEMPTS = 200
FXA_CONFIG = settings.FXA_CONFIG[settings.DEFAULT_FXA_CONFIG_NAME]


class DeveloperTaskSet(BaseUserTaskSet):

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
                '/en-US/developers/upload/',
                {'csrfmiddlewaretoken': csrfmiddlewaretoken},
                files={'upload': addon_file},
                name='devhub.upload {}'.format(
                    os.path.basename(addon_file.name)),
                allow_redirects=False,
                catch_response=True)

            if response.status_code == 302:
                poll_url = response.headers['location']
                upload_uuid = gevent.spawn(
                    self.poll_upload_until_ready, poll_url
                ).get()
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

    def poll_upload_until_ready(self, url):
        for i in range(MAX_UPLOAD_POLL_ATTEMPTS):
            response = self.client.get(
                url, allow_redirects=False,
                name='/en-US/developers/upload/:uuid',
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
                    response.success()
                    return data['upload']
            else:
                return response.failure('Unexpected status: {}'.format(
                    response.status_code))
            gevent.sleep(1)
        else:
            response.failure('Upload did not complete in {} tries'.format(
                MAX_UPLOAD_POLL_ATTEMPTS))
