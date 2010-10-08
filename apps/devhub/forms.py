from django import forms
from django.forms.models import modelformset_factory, BaseModelFormSet

import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from addons.models import Addon, AddonUser, Charity
from translations.widgets import TranslationTextarea, TranslationTextInput
from translations.models import delete_translation
from versions.models import License


class AuthorForm(happyforms.ModelForm):

    class Meta:
        model = AddonUser
        exclude = ('addon')


class BaseAuthorFormSet(BaseModelFormSet):

    def is_valid(self):
        # clean() won't get called in is_valid() if all the rows are getting
        # deleted. We can't allow deleting everything.
        rv = super(BaseAuthorFormSet, self).is_valid()
        return rv and not any(self.errors) and not bool(self.non_form_errors())

    def clean(self):
        if any(self.errors):
            return
        data = [f.cleaned_data for f in self.forms
                if not f.cleaned_data.get('DELETE', False)]
        if not any(d['role'] == amo.AUTHOR_ROLE_OWNER for d in data):
            raise forms.ValidationError(_('Must have at least one owner.'))
        if not any(d['listed'] for d in data):
            raise forms.ValidationError(
                _('At least one author must be listed.'))


AuthorFormSet = modelformset_factory(AddonUser, formset=BaseAuthorFormSet,
                                     form=AuthorForm, can_delete=True)


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


class CharityForm(happyforms.ModelForm):

    class Meta:
        model = Charity


class ContribForm(happyforms.ModelForm):
    RECIPIENTS = (('dev', _lazy('The developers of this add-on')),
                  ('moz', _lazy('The Mozilla Foundation')),
                  ('org', _lazy('An organization of my choice')))

    recipient = forms.ChoiceField(choices=RECIPIENTS,
                                  widget=forms.RadioSelect())

    @staticmethod
    def initial(addon):
        if addon.charity:
            recip = 'moz' if addon.charity_id == amo.FOUNDATION_ORG else 'org'
        else:
            recip = 'dev'
        return {'recipient': recip,
                'annoying': addon.annoying or amo.CONTRIB_PASSIVE}

    class Meta:
        model = Addon
        fields = ('paypal_id', 'suggested_amount', 'annoying')
        widgets = {'annoying': forms.RadioSelect()}

    def clean(self):
        if self.cleaned_data['recipient'] == 'dev':
            check_paypal_id(self.cleaned_data['paypal_id'])
        return self.cleaned_data


def check_paypal_id(paypal_id):
    if not paypal_id:
        raise forms.ValidationError(
            _('PayPal id required to accept contributions.'))
