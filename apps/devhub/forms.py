import path
import socket

from django import forms
from django.conf import settings
from django.db.models import Q
from django.forms.models import modelformset_factory
from django.utils.safestring import mark_safe
from django.utils.encoding import force_unicode

import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy
from quieter_formset.formset import BaseModelFormSet

import amo
import addons.forms
import paypal
from addons.models import Addon, AddonUser, Charity, Preview
from amo.forms import AMOModelForm
from amo.widgets import EmailWidget
from applications.models import Application, AppVersion
from files.models import File, FileUpload, Platform
from files.utils import parse_addon
from translations.widgets import TranslationTextarea, TranslationTextInput
from translations.fields import TransTextarea, TransField
from translations.models import delete_translation
from translations.forms import TranslationFormMixin
from versions.models import License, Version, ApplicationsVersions
from . import tasks


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


class DeleteForm(happyforms.Form):
    password = forms.CharField()

    def __init__(self, request):
        self.user = request.amo_user
        super(DeleteForm, self).__init__(request.POST)

    def clean_password(self):
        data = self.cleaned_data
        if not self.user.check_password(data['password']):
            raise forms.ValidationError(_('Password incorrect.'))


class LicenseChoiceRadio(forms.widgets.RadioFieldRenderer):

    def __iter__(self):
        for i, choice in enumerate(self.choices):
            yield LicenseRadioInput(self.name, self.value, self.attrs.copy(),
                                    choice, i)


class LicenseRadioInput(forms.widgets.RadioInput):

    def __init__(self, name, value, attrs, choice, index):
        super(LicenseRadioInput, self).__init__(name, value, attrs, choice,
                                                index)
        license = choice[1]  # Choice is a tuple (object.id, object).
        link = '<a class="xx extra" href="%s" target="_blank">%s</a>'
        if hasattr(license, 'url'):
            details = link % (license.url, _('Details'))
            self.choice_label = mark_safe(self.choice_label + details)


def LicenseForm(*args, **kw):
    # This needs to be lazy so we get the right translations.
    cs = [(x.builtin, x)
          for x in License.objects.builtins().filter(on_form=True)]
    cs.append((License.OTHER, _('Other')))

    class _Form(AMOModelForm):
        builtin = forms.TypedChoiceField(choices=cs, coerce=int,
            widget=forms.RadioSelect(attrs={'class': 'license'},
                                     renderer=LicenseChoiceRadio))
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


class PolicyForm(TranslationFormMixin, AMOModelForm):
    """Form for editing the add-ons EULA and privacy policy."""
    has_eula = forms.BooleanField(required=False,
        label=_lazy(u'This add-on has an End User License Agreement'))
    eula = TransField(widget=TransTextarea(), required=False,
        label=_lazy(u"Please specify your add-on's "
                    "End User License Agreement:"))
    has_priv = forms.BooleanField(
        required=False, label=_lazy(u"This add-on has a Privacy Policy"))
    privacy_policy = TransField(widget=TransTextarea(), required=False,
        label=_lazy(u"Please specify your add-on's Privacy Policy:"))

    class Meta:
        model = Addon
        fields = ('eula', 'privacy_policy')

    def save(self, commit=True):
        super(PolicyForm, self).save(commit)
        for k, field in (('has_eula', 'eula'), ('has_priv', 'privacy_policy')):
            if not self.cleaned_data[k]:
                delete_translation(self.instance, field)


def ProfileForm(*args, **kw):
     # If the add-on takes contributions, then both fields are required.
    fields_required = bool(kw['instance'].takes_contributions)
    fields_required = kw.pop('required', False) or fields_required

    class _Form(TranslationFormMixin, happyforms.ModelForm):
        the_reason = TransField(widget=TransTextarea(),
                                     required=fields_required,
                                     label=_("Why did you make this add-on?"))
        the_future = TransField(widget=TransTextarea(),
                                     required=fields_required,
                                     label=_("What's next for this add-on?"))

        class Meta:
            model = Addon
            fields = ('the_reason', 'the_future')

    return _Form(*args, **kw)


class CharityForm(happyforms.ModelForm):
    url = Charity._meta.get_field('url').formfield(verify_exists=False)

    class Meta:
        model = Charity

    def clean_paypal(self):
        check_paypal_id(self.cleaned_data['paypal'])
        return self.cleaned_data['paypal']

    def save(self, commit=True):
        # We link to the charity row in contrib stats, so we force all charity
        # changes to create a new row so we don't forget old charities.
        if self.changed_data and self.instance.id:
            self.instance.id = None
        return super(CharityForm, self).save(commit)


class ContribForm(TranslationFormMixin, happyforms.ModelForm):
    RECIPIENTS = (('dev', _lazy(u'The developers of this add-on')),
                  ('moz', _lazy(u'The Mozilla Foundation')),
                  ('org', _lazy(u'An organization of my choice')))

    recipient = forms.ChoiceField(choices=RECIPIENTS,
                    widget=forms.RadioSelect(attrs={'class': 'recipient'}))
    thankyou_note = TransField(widget=TransTextarea(), required=False)

    class Meta:
        model = Addon
        fields = ('paypal_id', 'suggested_amount', 'annoying',
                  'enable_thankyou', 'thankyou_note')
        widgets = {
            'annoying': forms.RadioSelect(),
            'suggested_amount': forms.TextInput(attrs={'class': 'short'}),
            'paypal_id': forms.TextInput(attrs={'size': '50'})
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
        # thankyou_note is a dict since it's a Translation.
        if not (data.get('enable_thankyou') and
                any(data.get('thankyou_note').values())):
            data['thankyou_note'] = {}
            data['enable_thankyou'] = False
        return data

    def clean_suggested_amount(self):
        amount = self.cleaned_data['suggested_amount']
        if amount is not None and amount <= 0:
            msg = _(u'Please enter a suggested amount greater than 0.')
            raise forms.ValidationError(msg)
        if amount > settings.MAX_CONTRIBUTION:
            msg = _(u'Please enter a suggested amount less than ${0}.').format(
                    settings.MAX_CONTRIBUTION)
            raise forms.ValidationError(msg)
        return amount


def check_paypal_id(paypal_id):
    if not paypal_id:
        raise forms.ValidationError(
            _('PayPal ID required to accept contributions.'))
    try:
        valid, msg = paypal.check_paypal_id(paypal_id)
        if not valid:
            raise forms.ValidationError(msg)
    except socket.error:
        raise forms.ValidationError(_('Could not validate PayPal id.'))


class VersionForm(happyforms.ModelForm):
    releasenotes = TransField(
        widget=TransTextarea(), required=False)
    approvalnotes = forms.CharField(
        widget=TranslationTextarea(attrs={'rows': 4}), required=False)

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
        self.app = amo.APPS_ALL[int(app)]
        qs = AppVersion.objects.filter(application=app).order_by('version_int')
        self.fields['min'].queryset = qs.filter(~Q(version__contains='*'))
        self.fields['max'].queryset = qs.all()

    def clean(self):
        min = self.cleaned_data.get('min')
        max = self.cleaned_data.get('max')
        if not (min and max and min.version_int <= max.version_int):
            raise forms.ValidationError(_('Invalid version range.'))
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
        apps = filter(None, [f.cleaned_data for f in self.forms
                             if not f.cleaned_data.get('DELETE', False)])
        if not apps:
            raise forms.ValidationError(
                _('Need at least one compatible application.'))


CompatFormSet = modelformset_factory(
    ApplicationsVersions, formset=BaseCompatFormSet,
    form=CompatForm, can_delete=True, extra=0)


class NewAddonForm(happyforms.Form):
    upload = forms.ModelChoiceField(widget=forms.HiddenInput,
        queryset=FileUpload.objects.filter(valid=True),
        error_messages={'invalid_choice': _lazy('There was an error with your '
                                                'upload. Please try again.')})
    desktop_platforms = forms.ModelMultipleChoiceField(
            queryset=Platform.objects,
            widget=forms.CheckboxSelectMultiple(attrs={'class': 'platform'}),
            initial=[amo.PLATFORM_ALL.id],
            required=False)
    desktop_platforms.choices = ((p.id, p.name)
                                 for p in amo.DESKTOP_PLATFORMS.values())
    mobile_platforms = forms.ModelMultipleChoiceField(
            queryset=Platform.objects,
            widget=forms.CheckboxSelectMultiple(attrs={'class': 'platform'}),
            required=False)
    mobile_platforms.choices = ((p.id, p.name)
                                for p in amo.MOBILE_PLATFORMS.values())

    def clean(self):
        if not self.errors:
            xpi = parse_addon(self.cleaned_data['upload'].path)
            addons.forms.clean_name(xpi['name'])
            self._clean_all_platforms()
        return self.cleaned_data

    def _clean_all_platforms(self):
        if (not self.cleaned_data['desktop_platforms']
            and not self.cleaned_data['mobile_platforms']):
            raise forms.ValidationError(_('Need at least one platform.'))


class NewVersionForm(NewAddonForm):

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        super(NewVersionForm, self).__init__(*args, **kw)

    def clean(self):
        if not self.errors:
            xpi = parse_addon(self.cleaned_data['upload'].path, self.addon)
            if self.addon.versions.filter(version=xpi['version']):
                raise forms.ValidationError(
                    _('Version %s already exists') % xpi['version'])
            self._clean_all_platforms()
        return self.cleaned_data


class NewFileForm(happyforms.Form):
    upload = forms.ModelChoiceField(widget=forms.HiddenInput,
        queryset=FileUpload.objects.filter(valid=True),
        error_messages={'invalid_choice': _lazy('There was an error with your '
                                                'upload. Please try again.')})
    platform = File._meta.get_field('platform').formfield(empty_label=None,
                    widget=forms.RadioSelect(attrs={'class': 'platform'}))
    platform.choices = sorted((p.id, p.name)
                              for p in amo.SUPPORTED_PLATFORMS.values())

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        self.version = kw.pop('version')
        super(NewFileForm, self).__init__(*args, **kw)
        # Reset platform choices to just those compatible with target app.
        field = self.fields['platform']
        field.choices = sorted((k, v.name) for k, v in
                               self.version.compatible_platforms().items())
        # Don't allow platforms we already have.
        to_exclude = set(File.objects.filter(version=self.version)
                                     .values_list('platform', flat=True))
        # Don't allow platform=ALL if we already have platform files.
        if len(to_exclude):
            to_exclude.add(amo.PLATFORM_ALL.id)

        # Always exclude PLATFORM_ALL_MOBILE because it's not supported for
        # downloads yet. The developer can choose Android + Maemo for now.
        # TODO(Kumar) Allow this option when it's supported everywhere.
        # See bug 646268.
        to_exclude.add(amo.PLATFORM_ALL_MOBILE.id)

        field.choices = [p for p in field.choices if p[0] not in to_exclude]
        field.queryset = Platform.objects.filter(id__in=dict(field.choices))

    def clean(self):
        if not self.version.is_allowed_upload():
            raise forms.ValidationError(
                _('You cannot upload any more files for this version.'))

        # Check for errors in the xpi.
        if not self.errors:
            xpi = parse_addon(self.cleaned_data['upload'].path, self.addon)
            if xpi['version'] != self.version.version:
                raise forms.ValidationError(_("Version doesn't match"))
        return self.cleaned_data


class FileForm(happyforms.ModelForm):
    platform = File._meta.get_field('platform').formfield(empty_label=None)

    class Meta:
        model = File
        fields = ('platform',)

    def __init__(self, *args, **kw):
        super(FileForm, self).__init__(*args, **kw)
        if kw['instance'].version.addon.type == amo.ADDON_SEARCH:
            del self.fields['platform']
        else:
            compat = kw['instance'].version.compatible_platforms()
            # TODO(Kumar) Allow PLATFORM_ALL_MOBILE when it's supported.
            # See bug 646268.
            if amo.PLATFORM_ALL_MOBILE.id in compat:
                del compat[amo.PLATFORM_ALL_MOBILE.id]
            pid = int(kw['instance'].platform_id)
            plats = [(p.id, p.name) for p in compat.values()]
            if pid not in compat:
                plats.append([pid, amo.PLATFORMS[pid].name])
            self.fields['platform'].choices = plats


class BaseFileFormSet(BaseModelFormSet):

    def clean(self):
        if any(self.errors):
            return
        files = [f.cleaned_data for f in self.forms
                 if not f.cleaned_data.get('DELETE', False)]

        if self.forms and 'platform' in self.forms[0].fields:
            platforms = [f['platform'].id for f in files]

            if amo.PLATFORM_ALL.id in platforms and len(files) > 1:
                raise forms.ValidationError(
                    _('The platfom All cannot be combined '
                      'with specific platforms.'))

            if sorted(platforms) != sorted(set(platforms)):
                raise forms.ValidationError(
                    _('A platform can only be chosen once.'))


FileFormSet = modelformset_factory(File, formset=BaseFileFormSet,
                                   form=FileForm, can_delete=True, extra=0)


class ReviewTypeForm(forms.Form):
    _choices = [(k, amo.STATUS_CHOICES[k]) for k in
                (amo.STATUS_UNREVIEWED, amo.STATUS_NOMINATED)]
    review_type = forms.TypedChoiceField(
        choices=_choices, widget=forms.HiddenInput,
        coerce=int, empty_value=None,
        error_messages={'required': 'A review type must be selected.'})


class Step3Form(addons.forms.AddonFormBasic):
    description = TransField(widget=TransTextarea, required=False)

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'summary', 'tags', 'description')


class PreviewForm(happyforms.ModelForm):
    caption = TransField(widget=TransTextarea, required=False)
    file_upload = forms.FileField(required=False)
    upload_hash = forms.CharField(required=False)

    def save(self, addon, commit=True):
        if self.cleaned_data:
            self.instance.addon = addon
            if self.cleaned_data.get('DELETE'):
                # Existing preview.
                if self.instance.id:
                    self.instance.delete()
                # User has no desire to save this preview.
                return

            super(PreviewForm, self).save(commit=commit)

            if self.cleaned_data['upload_hash']:
                upload_hash = self.cleaned_data['upload_hash']
                upload_path = path.path(settings.TMP_PATH) / 'preview' / upload_hash
                tasks.resize_preview.delay(str(upload_path),
                                           self.instance.thumbnail_path,
                                           self.instance.image_path)

    class Meta:
        model = Preview
        fields = ('caption', 'file_upload', 'upload_hash', 'id', 'position')


class BasePreviewFormSet(BaseModelFormSet):

    def clean(self):
        if any(self.errors):
            return


PreviewFormSet = modelformset_factory(Preview, formset=BasePreviewFormSet,
                                      form=PreviewForm, can_delete=True,
                                      extra=1)


class AdminForm(happyforms.ModelForm):
    type = forms.ChoiceField(choices=amo.ADDON_TYPE.items())

    # Request is needed in other ajax forms so we're stuck here.
    def __init__(self, request=None, *args, **kw):
        super(AdminForm, self).__init__(*args, **kw)

    class Meta:
        model = Addon
        fields = ('trusted', 'type', 'guid',
                  'target_locale', 'locale_disambiguation')
        widgets = {
            'guid': forms.TextInput(attrs={'size': '50'})
        }


class InlineRadioRenderer(forms.widgets.RadioFieldRenderer):

    def render(self):
        return mark_safe(''.join(force_unicode(w) for w in self))


class NewsletterForm(forms.Form):
    def __init__(self, *args, **kwargs):
        regions = kwargs.pop('regions')
        super(NewsletterForm, self).__init__(*args, **kwargs)
        self.fields['region'].choices = regions

    email = forms.EmailField(
        widget=EmailWidget(placeholder=_lazy(u'Your Email Address')))
    region = forms.ChoiceField(initial='us')
    format = forms.ChoiceField(
        widget=forms.widgets.RadioSelect(renderer=InlineRadioRenderer),
        choices=(('html', _lazy(u'HTML')),
                 ('text', _lazy(u'Text'))))
    policy = forms.BooleanField()
