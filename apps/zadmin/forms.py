import json
import os
import re
import urllib2

from django import forms
from django.conf import settings
from django.forms import ModelForm
from django.forms.models import modelformset_factory
from django.template import Context, Template, TemplateSyntaxError

import commonware.log
import happyforms
from piston.models import Consumer
from product_details import product_details
from tower import ugettext_lazy as _lazy
from quieter_formset.formset import BaseModelFormSet

import amo
from addons.models import Addon
from amo.urlresolvers import reverse
from applications.models import Application, AppVersion
from bandwagon.models import Collection, FeaturedCollection, MonthlyPick
from compat.forms import CompatForm as BaseCompatForm
from files.models import File
from zadmin.models import SiteEvent, ValidationJob

from .helpers import MassDeleteHelper

LOGGER_NAME = 'z.zadmin'
log = commonware.log.getLogger(LOGGER_NAME)


class DevMailerForm(happyforms.Form):
    _choices = [('eula',
                 'Developers who have set up EULAs for active add-ons'),
                ('sdk', 'Developers of active SDK add-ons'),
                ('all_extensions', 'All extension developers')]
    recipients = forms.ChoiceField(choices=_choices, required=True)
    subject = forms.CharField(widget=forms.TextInput(attrs=dict(size='100')),
                              required=True)
    preview_only = forms.BooleanField(initial=True, required=False,
                                      label=u'Log emails instead of sending')
    message = forms.CharField(widget=forms.Textarea, required=True)


class BulkValidationForm(happyforms.ModelForm):
    application = forms.ChoiceField(
                label=_lazy(u'Application'),
                choices=[(a.id, a.pretty) for a in amo.APPS_ALL.values()])
    curr_max_version = forms.ChoiceField(
                label=_lazy(u'Current Max. Version'),
                choices=[('', _lazy(u'Select an application first'))])
    target_version = forms.ChoiceField(
                label=_lazy(u'Target Version'),
                choices=[('', _lazy(u'Select an application first'))])
    finish_email = forms.CharField(required=False,
                                   label=_lazy(u'Email when finished'))

    class Meta:
        model = ValidationJob
        fields = ('application', 'curr_max_version', 'target_version',
                  'finish_email')

    def __init__(self, *args, **kw):
        kw.setdefault('initial', {})
        kw['initial']['finish_email'] = settings.FLIGTAR
        super(BulkValidationForm, self).__init__(*args, **kw)
        w = self.fields['application'].widget
        # Get the URL after the urlconf has loaded.
        w.attrs['data-url'] = reverse('zadmin.application_versions_json')

    def version_choices_for_app_id(self, app_id):
        versions = AppVersion.objects.filter(application__id=app_id)
        return [(v.id, v.version) for v in versions]

    def clean_application(self):
        app_id = int(self.cleaned_data['application'])
        app = Application.objects.get(pk=app_id)
        self.cleaned_data['application'] = app
        choices = self.version_choices_for_app_id(app_id)
        self.fields['target_version'].choices = choices
        self.fields['curr_max_version'].choices = choices
        return self.cleaned_data['application']

    def _clean_appversion(self, field):
        return AppVersion.objects.get(pk=int(field))

    def clean_curr_max_version(self):
        return self._clean_appversion(self.cleaned_data['curr_max_version'])

    def clean_target_version(self):
        return self._clean_appversion(self.cleaned_data['target_version'])


path = os.path.join(settings.ROOT, 'apps/zadmin/templates/zadmin')
texts = {
    'validation': open('%s/%s' % (path, 'validation-email.txt')).read(),
}


varname = re.compile(r'{{\s*([a-zA-Z0-9_]+)\s*}}')


class NotifyForm(happyforms.Form):
    subject = forms.CharField(widget=forms.TextInput, required=True)
    preview_only = forms.BooleanField(initial=True, required=False,
                            label=_lazy(u'Log emails instead of sending'))
    text = forms.CharField(widget=forms.Textarea, required=True)
    variables = ['{{PASSING_ADDONS}}', '{{FAILING_ADDONS}}', '{{APPLICATION}}',
                 '{{VERSION}}']
    variable_names = [varname.match(v).group(1) for v in variables]

    def __init__(self, *args, **kw):
        kw.setdefault('initial', {})
        if 'text' in kw:
            kw['initial']['text'] = texts[kw.pop('text')]
        kw['initial']['subject'] = ('Add-on compatibility with '
                                    '{{APPLICATION}} {{VERSION}}')
        super(NotifyForm, self).__init__(*args, **kw)

    def check_template(self, data):
        try:
            Template(data).render(Context({}))
        except TemplateSyntaxError, err:
            raise forms.ValidationError(err)
        return data

    def clean_text(self):
        return self.check_template(self.cleaned_data['text'])

    def clean_subject(self):
        return self.check_template(self.cleaned_data['subject'])


class MassDeleteForm(happyforms.Form):
    urls = forms.CharField(label=_lazy(u'URLs to delete'),
                           widget=forms.Textarea, required=True)
    reason = forms.CharField(label=_lazy(u'Reason for deletion'),
                             required=True)


class MassDeleteConfirmForm(happyforms.Form):
    objects = forms.CharField(widget=forms.HiddenInput, required=True)
    reason = forms.CharField(widget=forms.HiddenInput, required=True)

    def clean_objects(self):
        try:
            data = json.loads(self.cleaned_data.get('objects'))
        except ValueError:
            raise forms.ValidationError(
                u'Invalid objects JSON')

        if not all(all(isinstance(id_, int) for id_ in ids)
                   for ids in data.values()):
            raise forms.ValidationError(
                u'Invalid objects JSON')

        for m, ids in data.items():
            if m not in MassDeleteHelper.MODEL_MAP:
                raise forms.ValidationError(
                    u'Invalid model in objects JSON')

            # Purge dups
            ids = set(ids)

            model = MassDeleteHelper.MODEL_MAP[m]
            objs = model.objects.in_bulk(ids)
            if len(objs) != len(ids):
                raise forms.ValidationError(
                    u'Invalid IDs in objects JSON')

            data[m] = [objs[i] for i in ids]

        return data


class FeaturedCollectionForm(happyforms.ModelForm):
    LOCALES = (('', u'(Default Locale)'),) + tuple(
        (i, product_details.languages[i]['native'])
        for i in settings.AMO_LANGUAGES)

    application = forms.ModelChoiceField(Application.objects.all())
    collection = forms.CharField(widget=forms.HiddenInput)
    locale = forms.ChoiceField(choices=LOCALES, required=False)

    class Meta:
        model = FeaturedCollection
        fields = ('application', 'locale')

    def clean_collection(self):
        application = self.cleaned_data.get('application', None)
        collection = self.cleaned_data.get('collection', None)
        if not Collection.objects.filter(id=collection,
                                         application=application).exists():
            raise forms.ValidationError(
                u'Invalid collection for this application.')
        return collection

    def save(self, commit=False):
        collection = self.cleaned_data['collection']
        f = super(FeaturedCollectionForm, self).save(commit=commit)
        f.collection = Collection.objects.get(id=collection)
        f.save()
        return f


class BaseFeaturedCollectionFormSet(BaseModelFormSet):

    def __init__(self, *args, **kw):
        super(BaseFeaturedCollectionFormSet, self).__init__(*args, **kw)
        for form in self.initial_forms:
            try:
                form.initial['collection'] = (FeaturedCollection.objects
                    .get(id=form.instance.id).collection.id)
            except (FeaturedCollection.DoesNotExist, Collection.DoesNotExist):
                form.initial['collection'] = None


FeaturedCollectionFormSet = modelformset_factory(FeaturedCollection,
    form=FeaturedCollectionForm, formset=BaseFeaturedCollectionFormSet,
    can_delete=True, extra=0)


class OAuthConsumerForm(happyforms.ModelForm):

    class Meta:
        model = Consumer
        fields = ['name', 'description', 'status']


class MonthlyPickForm(happyforms.ModelForm):
    image = forms.CharField(required=False)
    blurb = forms.CharField(max_length=200,
                            widget=forms.Textarea(attrs={'cols': 20,
                                                         'rows': 2}))

    class Meta:
        model = MonthlyPick
        widgets = {
            'addon': forms.TextInput(),
        }
        fields = ('addon', 'image', 'blurb', 'locale')


MonthlyPickFormSet = modelformset_factory(MonthlyPick, form=MonthlyPickForm,
                                          can_delete=True, extra=0)


class AddonStatusForm(ModelForm):
    class Meta:
        model = Addon
        fields = ('status', 'highest_status', 'outstanding')


class FileStatusForm(ModelForm):
    class Meta:
        model = File
        fields = ('status',)


FileFormSet = modelformset_factory(File, form=FileStatusForm,
                                   formset=BaseModelFormSet, extra=0)


class JetpackUpgradeForm(happyforms.Form):
    minver = forms.CharField()
    maxver = forms.CharField()

    def __init__(self, *args, **kw):
        super(JetpackUpgradeForm, self).__init__(*args, **kw)
        fields = self.fields
        url = settings.BUILDER_VERSIONS_URL
        try:
            page = urllib2.urlopen(url)
            choices = [('', '')] + [(v, v) for v in json.loads(page.read())]
            fields['minver'] = fields['maxver'] = forms.ChoiceField()
            fields['minver'].choices = fields['maxver'].choices = choices
        except urllib2.URLError, e:
            log.error('Could not open %r: %s' % (url, e))
        except ValueError, e:
            log.error('Could not parse %r: %s' % (url, e))
        if not ('minver' in self.data or 'maxver' in self.data):
            fields['minver'].required = fields['maxver'].required = False

    def clean(self):
        if not self.errors:
            minver = self.cleaned_data.get('minver')
            maxver = self.cleaned_data.get('maxver')
            if minver and maxver and minver >= maxver:
                raise forms.ValidationError('Invalid version range.')
        return self.cleaned_data


class SiteEventForm(ModelForm):
    class Meta:
        model = SiteEvent
        fields = ('start', 'end', 'event_type', 'description',
                  'more_info_url')


class YesImSure(happyforms.Form):
    yes = forms.BooleanField(required=True, label="Yes, I'm sure")


class CompatForm(BaseCompatForm):
    _minimum_choices = [(x, x) for x in xrange(100, -10, -10)]
    minimum = forms.TypedChoiceField(choices=_minimum_choices, coerce=int,
                                     required=False)
    _ratio_choices = [('%.1f' % (x / 10.0), '%.0f%%' % (x * 10))
                      for x in xrange(9, -1, -1)]
    ratio = forms.ChoiceField(choices=_ratio_choices, required=False)


class GenerateErrorForm(happyforms.Form):
    error = forms.ChoiceField(choices=(
                    ['zerodivisionerror', 'Zero Division Error (will email)'],
                    ['iorequesterror', 'IORequest Error (no email)'],
                    ['heka_statsd', 'Heka statsd message'],
                    ['heka_json', 'Heka JSON message'],
                    ['heka_cef', 'Heka CEF message'],
                    ['heka_sentry', 'Heka Sentry message'],
                    ['amo_cef', 'AMO CEF message'],
                    ))

    def explode(self):
        error = self.cleaned_data.get('error')

        if error == 'zerodivisionerror':
            1 / 0
        elif error == 'iorequesterror':
            class IOError(Exception):
                pass
            raise IOError('request data read error')
        elif error == 'heka_cef':
            environ = {'REMOTE_ADDR': '127.0.0.1', 'HTTP_HOST': '127.0.0.1',
                            'PATH_INFO': '/', 'REQUEST_METHOD': 'GET',
                            'HTTP_USER_AGENT': 'MySuperBrowser'}

            config = {'cef.version': '0',
                           'cef.vendor': 'Mozilla',
                           'cef.device_version': '3',
                           'cef.product': 'zamboni',
                           'cef': True}

            settings.HEKA.cef('xx\nx|xx\rx', 5, environ, config,
                    username='me', ext1='ok=ok', ext2='ok\\ok',
                    logger_info='settings.HEKA')
        elif error == 'heka_statsd':
            settings.HEKA.incr(name=LOGGER_NAME)
        elif error == 'heka_json':
            settings.HEKA.heka(type="heka_json",
                    fields={'foo': 'bar', 'secret': 42,
                            'logger_type': 'settings.HEKA'})

        elif error == 'heka_sentry':
            # These are local variables only used
            # by Sentry's frame hacking magic.
            # They won't be referenced which may trigger flake8
            # errors.
            heka_conf = settings.HEKA_CONF  # NOQA
            active_heka_conf = settings.HEKA._config  # NOQA
            try:
                1 / 0
            except:
                settings.HEKA.raven('heka_sentry error triggered')
        elif error == 'amo_cef':
            from amo.utils import log_cef
            env = {'REMOTE_ADDR': '127.0.0.1', 'HTTP_HOST': '127.0.0.1',
                            'PATH_INFO': '/', 'REQUEST_METHOD': 'GET',
                            'HTTP_USER_AGENT': 'MySuperBrowser'}
            log_cef(settings.STATSD_PREFIX, 6, env)


class PriceTiersForm(happyforms.Form):
    prices = forms.FileField()
