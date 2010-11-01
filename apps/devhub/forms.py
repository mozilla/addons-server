import socket

from django import forms
from django.db.models import Q
from django.forms.models import modelformset_factory, BaseModelFormSet

import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy

import amo
import paypal
from addons.models import Addon, AddonUser, Charity
from applications.models import Application, AppVersion
from files.models import File
from translations.widgets import TranslationTextarea, TranslationTextInput
from translations.models import delete_translation
from versions.models import License, Version, ApplicationsVersions


class AuthorForm(happyforms.ModelForm):

    class Meta:
        model = AddonUser
        exclude = ('addon')


class BaseModelFormSet(BaseModelFormSet):
    """
    Override the parent's is_valid to prevent deleting all forms.
    """

    def is_valid(self):
        # clean() won't get called in is_valid() if all the rows are getting
        # deleted. We can't allow deleting everything.
        rv = super(BaseModelFormSet, self).is_valid()
        return rv and not any(self.errors) and not bool(self.non_form_errors())


class BaseAuthorFormSet(BaseModelFormSet):

    def clean(self):
        if any(self.errors):
            return
        # cleaned_data could be None if it's the empty extra form.
        data = filter(None, [f.cleaned_data for f in self.forms
                             if not f.cleaned_data.get('DELETE', False)])
        if not any(d['role'] == amo.AUTHOR_ROLE_OWNER for d in data):
            raise forms.ValidationError(_('Must have at least one owner.'))
        if not any(d['listed'] for d in data):
            raise forms.ValidationError(
                _('At least one author must be listed.'))
        users = [d['user'] for d in data]
        if sorted(users) != sorted(set(users)):
            raise forms.ValidationError(
                _('An author can only be listed once.'))


AuthorFormSet = modelformset_factory(AddonUser, formset=BaseAuthorFormSet,
                                     form=AuthorForm, can_delete=True, extra=0)


def LicenseForm(*args, **kw):
    # This needs to be lazy so we get the right translations.
    cs = [(x.builtin, x.name)
          for x in License.objects.builtins().filter(on_form=True)]
    cs.append((License.OTHER, _('Other')))

    class _Form(happyforms.ModelForm):
        builtin = forms.TypedChoiceField(choices=cs, coerce=int,
            widget=forms.RadioSelect(attrs={'class': 'license'}))
        name = forms.CharField(widget=TranslationTextInput(),
                               label=_("What is your license's name?"),
                               required=False, initial=_('Custom License'))
        text = forms.CharField(widget=TranslationTextarea(), required=False,
                               label=_('Provide the text of your license.'))

        class Meta:
            model = License
            fields = ('builtin', 'name', 'text')

        def clean_name(self):
            name = self.cleaned_data['name']
            return name.strip() or _('Custom License')

        def clean(self):
            data = self.cleaned_data
            if self.errors:
                return data
            elif data['builtin'] == License.OTHER and not data['text']:
                raise forms.ValidationError(
                    _('License text is required when choosing Other.'))
            return data

        def save(self, commit=True):
            builtin = self.cleaned_data['builtin']
            if builtin != License.OTHER:
                return License.objects.get(builtin=builtin)
            return super(_Form, self).save(commit)

    return _Form(*args, **kw)


class PolicyForm(happyforms.ModelForm):
    """Form for editing the add-ons EULA and privacy policy."""
    has_eula = forms.BooleanField(required=False,
        label=_('This add-on has an End User License Agreement'))
    eula = forms.CharField(widget=TranslationTextarea(), required=False,
        label=_("Please specify your add-on's End User License Agreement:"))
    has_priv = forms.BooleanField(required=False,
                                  label=_("This add-on has a Privacy Policy"))
    privacy_policy = forms.CharField(
        widget=TranslationTextarea(), required=False,
        label=_("Please specify your add-on's privacy policy:"))

    class Meta:
        model = Addon
        fields = ('eula', 'privacy_policy')

    def save(self, addon, commit=True):
        super(PolicyForm, self).save(commit)
        for k, field in (('has_eula', 'eula'), ('has_priv', 'privacy_policy')):
            if not self.cleaned_data[k]:
                delete_translation(addon, field)


def ProfileForm(*args, **kw):
     # If the add-on takes contributions, then both fields are required.
    fields_required = bool(kw['instance'].takes_contributions)

    class _Form(happyforms.ModelForm):
        the_reason = forms.CharField(widget=TranslationTextarea(),
                                     required=fields_required,
                                     label=_("Why did you make this add-on?"))
        the_future = forms.CharField(widget=TranslationTextarea(),
                                     required=fields_required,
                                     label=_("What's next for this add-on?"))

        class Meta:
            model = Addon
            fields = ('the_reason', 'the_future')

    return _Form(*args, **kw)


class CharityForm(happyforms.ModelForm):

    class Meta:
        model = Charity

    def clean_paypal(self):
        check_paypal_id(self.cleaned_data['paypal'])
        return self.cleaned_data['paypal']


class ContribForm(happyforms.ModelForm):
    RECIPIENTS = (('dev', _lazy('The developers of this add-on')),
                  ('moz', _lazy('The Mozilla Foundation')),
                  ('org', _lazy('An organization of my choice')))

    recipient = forms.ChoiceField(choices=RECIPIENTS,
                    widget=forms.RadioSelect(attrs={'class': 'recipient'}))
    thankyou_note = forms.CharField(widget=TranslationTextarea(),
                                    required=False)

    class Meta:
        model = Addon
        fields = ('paypal_id', 'suggested_amount', 'annoying',
                  'enable_thankyou', 'thankyou_note')
        widgets = {
            'annoying': forms.RadioSelect(),
            'suggested_amount': forms.TextInput(attrs={'class': 'short'}),
        }

    @staticmethod
    def initial(addon):
        if addon.charity:
            recip = 'moz' if addon.charity_id == amo.FOUNDATION_ORG else 'org'
        else:
            recip = 'dev'
        return {'recipient': recip,
                'annoying': addon.annoying or amo.CONTRIB_PASSIVE}

    def clean(self):
        data = self.cleaned_data
        try:
            if not self.errors and data['recipient'] == 'dev':
                check_paypal_id(data['paypal_id'])
        except forms.ValidationError, e:
            self.errors['paypal_id'] = self.error_class(e.messages)
        if not (data.get('enable_thankyou') and data.get('thankyou_note')):
            data['thankyou_note'] = None
            data['enable_thankyou'] = False
        return data


def check_paypal_id(paypal_id):
    if not paypal_id:
        raise forms.ValidationError(
            _('PayPal id required to accept contributions.'))
    try:
        valid, msg = paypal.check_paypal_id(paypal_id)
        if not valid:
            raise forms.ValidationError(msg)
    except socket.error:
        raise forms.ValidationError(_('Could not validate PayPal id.'))


class VersionForm(happyforms.ModelForm):
    releasenotes = forms.CharField(widget=TranslationTextarea(),
                                   required=False)

    class Meta:
        model = Version
        fields = ('releasenotes', 'approvalnotes')


class ApplicationChoiceField(forms.ModelChoiceField):

    def label_from_instance(self, obj):
        return obj.id


class AppVersionChoiceField(forms.ModelChoiceField):

    def label_from_instance(self, obj):
        return obj.version


class CompatForm(happyforms.ModelForm):
    application = ApplicationChoiceField(Application.objects.all(),
                                         widget=forms.HiddenInput)
    min = AppVersionChoiceField(AppVersion.objects.none())
    max = AppVersionChoiceField(AppVersion.objects.none())

    class Meta:
        model = ApplicationsVersions
        fields = ('application', 'min', 'max')

    def __init__(self, *args, **kw):
        super(CompatForm, self).__init__(*args, **kw)
        if self.initial:
            app = self.initial['application']
        else:
            app = self.data[self.add_prefix('application')]
        self.app = amo.APP_IDS[int(app)]
        qs = AppVersion.objects.filter(application=app).order_by('version_int')
        self.fields['min'].queryset = qs.filter(~Q(version__contains='*'))
        self.fields['max'].queryset = qs.all()

    def clean(self):
        min = self.cleaned_data.get('min')
        max = self.cleaned_data.get('max')
        if not (min and max and min.version_int < max.version_int):
            raise forms.ValidationError(_('Invalid version range'))
        return self.cleaned_data


class BaseCompatFormSet(BaseModelFormSet):

    def __init__(self, *args, **kw):
        super(BaseCompatFormSet, self).__init__(*args, **kw)
        # We always want a form for each app, so force extras for apps
        # the add-on does not already have.
        qs = kw['queryset'].values_list('application', flat=True)
        apps = [a for a in amo.APP_USAGE if a.id not in qs]
        self.initial = ([{} for _ in qs] +
                        [{'application': a.id} for a in apps])
        self.extra = len(amo.APP_GUIDS) - len(self.forms)
        self._construct_forms()

    def clean(self):
        if any(self.errors):
            return
        apps = [f for f in self.forms
                if not f.cleaned_data.get('DELETE', False)]
        if not apps:
            raise forms.ValidationError(
                _('Need at least one compatible application.'))


CompatFormSet = modelformset_factory(
    ApplicationsVersions, formset=BaseCompatFormSet,
    form=CompatForm, can_delete=True, extra=0)


class FileForm(happyforms.ModelForm):
    _choices = [(k, amo.STATUS_CHOICES[k]) for k in
                (amo.STATUS_BETA, amo.STATUS_UNREVIEWED)]
    status = forms.TypedChoiceField(coerce=int, choices=_choices)
    platform = File._meta.get_field('platform').formfield(empty_label=None)

    class Meta:
        model = File
        fields = ('status', 'platform')

    def __init__(self, *args, **kw):
        super(FileForm, self).__init__(*args, **kw)
        # Make sure the current status is in the status <select>.
        status = kw['instance'].status
        field = self.fields['status']
        if status not in dict(field.choices).keys():
            # Rebind and add so the original choices aren't changed.
            field.choices = (field.choices +
                             [(status, amo.STATUS_CHOICES[status])])


class BaseFileFormSet(BaseModelFormSet):

    def clean(self):
        if any(self.errors):
            return
        files = [f.cleaned_data for f in self.forms
                 if not f.cleaned_data.get('DELETE', False)]
        platforms = [f['platform'] for f in files]
        if sorted(platforms) != sorted(set(platforms)):
            raise forms.ValidationError(
                _('A platform can only be chosen once.'))


FileFormSet = modelformset_factory(File, formset=BaseFileFormSet,
                                   form=FileForm, can_delete=True, extra=0)
