import os
import uuid
import zipfile

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage

import requests

from django_statsd.clients import statsd

import olympia.core.logger

from olympia.amo.templatetags.jinja_helpers import user_media_path
from olympia.files.utils import SafeZip


class GithubCallback(object):

    def __init__(self, data):
        if data['type'] != 'github':
            raise ValueError('Not a github callback.')
        self.data = data

    def get(self):
        log.info('Getting zip from github: {}'.format(self.data['zip_url']))
        with statsd.timer('github.zip'):
            res = requests.get(self.data['zip_url'])
            res.raise_for_status()
        return res

    def post(self, url, data):
        msg = data.get('state', 'comment')
        log.info('Setting github to: {} at: {}'.format(msg, url))
        with statsd.timer('github.{}'.format(msg)):
            data['context'] = 'mozilla/addons-linter'
            log.info('Body: {}'.format(data))
            res = requests.post(
                url,
                json=data,
                auth=(settings.GITHUB_API_USER, settings.GITHUB_API_TOKEN))
            log.info('Response: {}'.format(res.content))
            res.raise_for_status()

    def pending(self):
        self.post(self.data['status_url'], data={'state': 'pending'})

    def success(self, url):
        self.post(self.data['status_url'], data={
            'state': 'success',
            'target_url': url
        })

    def error(self, url):
        self.post(self.data['status_url'], data={
            'state': 'error',
            # Not localising because we aren't sure what locale to localise to.
            # I would like to pass a longer string here that shows more details
            # however, we are limited to "A short description of the status."
            # Which means all the fancy things I wanted to do got truncated.
            'description': 'This add-on did not validate.',
            'target_url': url
        })

    def failure(self):
        data = {
            'state': 'failure',
            # Not localising because we aren't sure what locale to localise to.
            'description': 'The validator failed to run correctly.'
        }
        self.post(self.data['status_url'], data=data)


class GithubRequest(forms.Form):
    status_url = forms.URLField(required=False)
    zip_url = forms.URLField(required=False)
    sha = forms.CharField(required=False)

    @property
    def repo(self):
        return self.data['pull_request']['head']['repo']

    @property
    def sha(self):
        return self.data['pull_request']['head']['sha']

    def get_status(self):
        return self.repo['statuses_url'].replace('{sha}', self.sha)

    def get_zip(self):
        return (
            self.repo['archive_url']
            .replace('{archive_format}', 'zipball')
            .replace('{/ref}', '/' + self.sha))

    def validate_url(self, url):
        if not url.startswith('https://api.github.com/'):
            raise forms.ValidationError('Invalid URL: {}'.format(url))
        return url

    def clean(self):
        fields = (
            ('status_url', self.get_status),
            ('zip_url', self.get_zip),
        )
        for url, method in fields:
            try:
                self.cleaned_data[url] = self.validate_url(method())
            except Exception:
                log.error('Invalid data in processing JSON')
                raise forms.ValidationError('Invalid data')

        self.cleaned_data['sha'] = self.data['pull_request']['head']['sha']
        self.cleaned_data['type'] = 'github'
        return self.cleaned_data


def rezip_file(response, pk):
    # An .xpi does not have a directory inside the zip, yet zips from github
    # do, so we'll need to rezip the file before passing it through to the
    # validator.
    loc = os.path.join(user_media_path('addons'), 'temp', uuid.uuid4().hex)
    old_filename = '{}_github_webhook.zip'.format(pk)
    old_path = os.path.join(loc, old_filename)

    with storage.open(old_path, 'wb') as old:
        old.write(response.content)

    new_filename = '{}_github_webhook.xpi'.format(pk)
    new_path = os.path.join(loc, new_filename)

    old_zip = SafeZip(old_path)
    if not old_zip.is_valid():
        raise

    with storage.open(new_path, 'w') as new:
        new_zip = zipfile.ZipFile(new, 'w')

        for obj in old_zip.filelist:
            # Basically strip off the leading directory.
            new_filename = obj.filename.partition('/')[-1]
            if not new_filename:
                continue
            new_zip.writestr(new_filename, old_zip.read(obj.filename))

        new_zip.close()

    old_zip.close()
    return new_path
