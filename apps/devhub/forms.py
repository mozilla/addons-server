from django import forms
from django.forms.models import modelformset_factory, BaseModelFormSet

import happyforms
from tower import ugettext as _

import amo
from addons.models import AddonUser
from translations.widgets import TranslationTextarea, TranslationTextInput
from versions.models import License


class AuthorForm(happyforms.ModelForm):

    class Meta:
        model = AddonUser
        exclude = ('addon', 'position')


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
                                         widget=forms.RadioSelect())
        name = forms.CharField(widget=TranslationTextInput(),
                               required=False, initial=_('Custom License'))
        text = forms.CharField(widget=TranslationTextarea(), required=False)

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
