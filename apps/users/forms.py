import logging
from django import forms
from django.forms.util import ErrorList
from django.contrib.auth import forms as auth_forms

from l10n import ugettext as _

from . import models

log = logging.getLogger('z.users')


class AuthenticationForm(auth_forms.AuthenticationForm):
    rememberme = forms.BooleanField(required=False)


class PasswordResetForm(auth_forms.PasswordResetForm):
    def save(self, **kw):
        for user in self.users_cache:
            log.info('Password reset email sent for user (%s)' % user)
        super(PasswordResetForm, self).save(**kw)


class SetPasswordForm(auth_forms.SetPasswordForm):
    def __init__(self, user, *args, **kwargs):
        super(SetPasswordForm, self).__init__(user, *args, **kwargs)
        if self.user:
            self.user = self.user.get_profile()

    def save(self, **kw):
        log.info('User (%s) changed password with reset form' % self.user)
        super(SetPasswordForm, self).save(**kw)


class UserEditForm(forms.ModelForm):
    oldpassword = forms.CharField(max_length=255, required=False,
                            widget=forms.PasswordInput(render_value=False))
    newpassword = forms.CharField(max_length=255, required=False,
                            widget=forms.PasswordInput(render_value=False))
    newpassword2 = forms.CharField(max_length=255, required=False,
                            widget=forms.PasswordInput(render_value=False))

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        return super(UserEditForm, self).__init__(*args, **kwargs)

    class Meta:
        model = models.UserProfile
        exclude = ['password']

    def clean(self):
        super(UserEditForm, self).clean()

        data = self.cleaned_data
        amouser = self.request.user.get_profile()

        p1 = data.get("newpassword")
        p2 = data.get("newpassword2")

        if p1 or p2:
            if not amouser.check_password(data["oldpassword"]):
                msg = _("Wrong password entered!")
                self._errors["oldpassword"] = ErrorList([msg])
                del data["oldpassword"]
            if p1 != p2:
                msg = _("The passwords did not match.")
                self._errors["newpassword2"] = ErrorList([msg])
                del data["newpassword"]
                del data["newpassword2"]

        return data

    def save(self):
        super(UserEditForm, self).save()
        data = self.cleaned_data
        amouser = self.request.user.get_profile()

        if data['newpassword']:
            amouser.set_password(data['newpassword'])
            log.info('User (%s) changed their password', amouser)

        log.debug('User (%s) updated their profile', amouser)

        amouser.save()
