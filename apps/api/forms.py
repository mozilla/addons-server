import json
import re

from django import forms

import happyforms

from addons.models import Addon
from api.handlers import _form_error

OS = ['WINNT', 'Darwin', 'Linux']
PLATFORMS = ['x86', 'x86_64']
PRODUCTS = ['firefox']
TESTS = ['ts']


def choices(x):
    return [(c, c) for c in x]

HASH_RE = re.compile(r'^[0-9a-f]{64}$', re.I)


class ChecksumsForm(happyforms.Form):
    checksum_json = forms.CharField(max_length=2 ** 24 - 1,  # MEDIUMTEXT max.
                                    required=True)

    def clean_checksum_json(self):
        # Do basic schema validation.
        data = json.loads(self.cleaned_data['checksum_json'])

        def check_messages(d):
            return ('messages' not in d or
                    isinstance(d['messages'], list) and
                    all(isinstance(m, basestring)
                        for m in d['messages']))

        for key in 'frameworks', 'libraries':
            if not isinstance(data.get(key), dict):
                raise forms.ValidationError('Key "%s" not in data' % key)

            for name, framework in data[key].iteritems():
                if not check_messages(framework):
                    raise forms.ValidationError(
                        'Invalid messages for %s' % name)

                if 'versions' not in framework:
                    continue

                if not isinstance(framework['versions'], dict):
                    raise forms.ValidationError(
                        'Invalid versions data for %s' % name)

                for ver_number, ver in framework['versions'].iteritems():
                    if not (isinstance(ver.get('files'), dict) and
                            check_messages(ver) and
                            all(filter(HASH_RE.match,
                                       ver['files'].itervalues()))):
                        raise forms.ValidationError('Invalid data for %s '
                                                    'version %s' % (ver_number,
                                                                    ver))

        if not isinstance(data.get('hashes'), dict):
            raise forms.ValidationError('No valid "hashes" dictionary')

        for hash, data in data['hashes'].iteritems():
            if not (HASH_RE.match(hash) and
                    isinstance(data, dict) and
                    isinstance(data.get('sources'), list) and
                    all(isinstance(s, list) and len(s) == 3 and
                        all(isinstance(x, basestring) for x in s)
                        for s in data['sources']) and
                    check_messages(data)):
                raise forms.ValidationError('Invalid data for hash %s' % hash)

        return data


class PerformanceForm(happyforms.Form):
    addon_id = forms.IntegerField(required=False)
    os = forms.ChoiceField(choices=choices(OS))
    version = forms.CharField(max_length=255)
    platform = forms.ChoiceField(choices=choices(PLATFORMS))
    product = forms.ChoiceField(choices=choices(PRODUCTS))
    product_version = forms.CharField(max_length=255)
    average = forms.FloatField()
    test = forms.ChoiceField(choices=choices(TESTS))

    def show_error(self):
        return _form_error(self)

    def clean_addon_id(self):
        if self.data.get('addon_id'):
            try:
                # Add addon into the form data, leaving addon_id alone.
                addon = Addon.objects.get(pk=self.data['addon_id'])
                self.cleaned_data['addon'] = addon
                return addon.pk
            except Addon.DoesNotExist:
                raise forms.ValidationError('Add-on not found: %s'
                                            % self.data['addon_id'])

    @property
    def os_version(self):
        return dict([k, self.cleaned_data[k]]
                    for k in ['os', 'version', 'platform'])

    @property
    def app_version(self):
        return {'app': self.cleaned_data['product'],
                'version': self.cleaned_data['product_version']}

    @property
    def performance(self):
        return dict([k, self.cleaned_data.get(k)] for k in ['addon', 'test'])
