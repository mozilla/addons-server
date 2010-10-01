from django import forms
from django.forms.models import modelformset_factory, BaseModelFormSet

from tower import ugettext as _

import amo
from addons.models import AddonUser


class AuthorForm(forms.ModelForm):

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
