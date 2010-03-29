import logging
from django import forms
from django.contrib.auth import forms as auth_forms
from django.forms.util import ErrorList

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


class UserDeleteForm(forms.Form):
    password = forms.CharField(max_length=255, required=True,
                            widget=forms.PasswordInput(render_value=False))
    confirm = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        return super(UserDeleteForm, self).__init__(*args, **kwargs)

    def clean_password(self):
        data = self.cleaned_data
        amouser = self.request.user.get_profile()
        if not amouser.check_password(data["password"]):
            raise forms.ValidationError(_("Wrong password entered!"))

    def clean_confirm(self):
        if not self.cleaned_data['confirm']:
            msg = _(('You need to check the box "I understand..." before we '
                     'can delete your account.'))
            raise forms.ValidationError(msg)

    def clean(self):
        amouser = self.request.user.get_profile()
        if amouser.is_developer:
            # This is tampering because the form isn't shown on the page if the
            # user is a developer
            log.warning('[Tampering] Attempt to delete developer account (%s)'
                                                          % self.request.user)
            raise forms.ValidationError("")

    def save(self, **kw):
        log.info('User (%s) has successfully deleted their account.'
                                                        % self.request.user)
        super(UserDeleteForm, self).save(**kw)


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

    def clean_nickname(self):
        """We're breaking the rules and allowing null=True and blank=True on a
        CharField because I want to enforce uniqueness in the db.  In order to
        let save() work, I override '' here."""
        n = self.cleaned_data['nickname']
        if n == '':
            n = None
        return n

    def clean(self):
        super(UserEditForm, self).clean()

        data = self.cleaned_data
        amouser = self.request.user.get_profile()

        # Passwords
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

        # Names
        if not "nickname" in self._errors:
            fname = data.get("firstname")
            lname = data.get("lastname")
            nname = data.get("nickname")
            if not (fname or lname or nname):
                msg = _("A first name, last name or nickname is required.")
                self._errors["firstname"] = ErrorList([msg])
                self._errors["lastname"] = ErrorList([msg])
                self._errors["nickname"] = ErrorList([msg])

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


class UserRegisterForm(forms.ModelForm):
    """For registering users.  We're not building off
    d.contrib.auth.forms.UserCreationForm because it doesn't do a lot of the
    details here, so we'd have to rewrite most of it anyway."""
    password = forms.CharField(max_length=255, required=False,
                            widget=forms.PasswordInput(render_value=False))
    password2 = forms.CharField(max_length=255, required=False,
                            widget=forms.PasswordInput(render_value=False))

    class Meta:
        model = models.UserProfile

    def clean_nickname(self):
        """We're breaking the rules and allowing null=True and blank=True on a
        CharField because I want to enforce uniqueness in the db.  In order to
        let save() work, I override '' here."""
        n = self.cleaned_data['nickname']
        if n == '':
            n = None
        return n

    def clean(self):
        super(UserRegisterForm, self).clean()

        data = self.cleaned_data

        # Passwords
        p1 = data.get("password")
        p2 = data.get("password2")

        if p1 != p2:
            msg = _("The passwords did not match.")
            self._errors["password2"] = ErrorList([msg])
            #del data["password"]
            del data["password2"]

        # Names
        if not ("nickname" in self._errors or
                "firstname" in self._errors or
                "lastname" in self._errors):
            fname = data.get("firstname")
            lname = data.get("lastname")
            nname = data.get("nickname")
            if not (fname or lname or nname):
                msg = _("A first name, last name or nickname is required.")
                self._errors["firstname"] = ErrorList([msg])
                self._errors["lastname"] = ErrorList([msg])
                self._errors["nickname"] = ErrorList([msg])

        return data
