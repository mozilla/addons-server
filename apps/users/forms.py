import os

from django import forms
from django.contrib.auth import forms as auth_forms
from django.forms.util import ErrorList

import commonware.log
from tower import ugettext as _

from .models import UserProfile, BlacklistedNickname

log = commonware.log.getLogger('z.users')


class AuthenticationForm(auth_forms.AuthenticationForm):
    rememberme = forms.BooleanField(required=False)


class PasswordResetForm(auth_forms.PasswordResetForm):
    def save(self, **kw):
        for user in self.users_cache:
            log.info(u'Password reset email sent for user (%s)' % user)
        super(PasswordResetForm, self).save(**kw)


class SetPasswordForm(auth_forms.SetPasswordForm):
    def __init__(self, user, *args, **kwargs):
        super(SetPasswordForm, self).__init__(user, *args, **kwargs)
        if self.user:
            # We store our password in the users table, not auth_user like
            # Django expects
            self.user = self.user.get_profile()

    def save(self, **kw):
        log.info(u'User (%s) changed password with reset form' % self.user)
        super(SetPasswordForm, self).save(**kw)


class UserDeleteForm(forms.Form):
    password = forms.CharField(max_length=255, required=True,
                            widget=forms.PasswordInput(render_value=False))
    confirm = forms.BooleanField(required=True)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(UserDeleteForm, self).__init__(*args, **kwargs)

    def clean_password(self):
        data = self.cleaned_data
        amouser = self.request.user.get_profile()
        if not amouser.check_password(data["password"]):
            raise forms.ValidationError(_("Wrong password entered!"))

    def clean(self):
        amouser = self.request.user.get_profile()
        if amouser.is_developer:
            # This is tampering because the form isn't shown on the page if the
            # user is a developer
            log.warning(u'[Tampering] Attempt to delete developer account (%s)'
                                                          % self.request.user)
            raise forms.ValidationError("")

    def save(self, **kw):
        log.info(u'User (%s) has successfully deleted their account.'
                                                        % self.request.user)
        super(UserDeleteForm, self).save(**kw)


class UserRegisterForm(forms.ModelForm):
    """For registering users.  We're not building off
    d.contrib.auth.forms.UserCreationForm because it doesn't do a lot of the
    details here, so we'd have to rewrite most of it anyway."""
    password = forms.CharField(max_length=255, required=False,
                            widget=forms.PasswordInput(render_value=False))
    password2 = forms.CharField(max_length=255, required=False,
                            widget=forms.PasswordInput(render_value=False))

    class Meta:
        model = UserProfile

    def clean_nickname(self):
        """We're breaking the rules and allowing null=True and blank=True on a
        CharField because I want to enforce uniqueness in the db.  In order to
        let save() work, I override '' here."""
        return self.cleaned_data['nickname'] or None

    def clean(self):
        super(UserRegisterForm, self).clean()

        data = self.cleaned_data

        # Passwords
        p1 = data.get("password")
        p2 = data.get("password2")

        if p1 != p2:
            msg = _("The passwords did not match.")
            self._errors["password2"] = ErrorList([msg])
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

            # Nickname could be blacklisted
            if ("nickname" not in self._errors
                and nname
                and BlacklistedNickname.blocked(nname)):
                msg = _("This nickname is invalid.")
                self._errors["nickname"] = ErrorList([msg])

        return data


class UserEditForm(UserRegisterForm):
    oldpassword = forms.CharField(max_length=255, required=False,
                            widget=forms.PasswordInput(render_value=False))

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(UserEditForm, self).__init__(*args, **kwargs)

    class Meta:
        model = UserProfile
        exclude = ['password']

    def clean(self):

        data = self.cleaned_data
        amouser = self.request.user.get_profile()

        # Passwords
        p1 = data.get("password")
        p2 = data.get("password2")

        if p1 or p2:
            if not amouser.check_password(data["oldpassword"]):
                msg = _("Wrong password entered!")
                self._errors["oldpassword"] = ErrorList([msg])
                del data["oldpassword"]

        super(UserEditForm, self).clean()
        return data

    def save(self):
        super(UserEditForm, self).save()
        data = self.cleaned_data
        amouser = self.request.user.get_profile()

        if data['password']:
            amouser.set_password(data['password'])
            log.info(u'User (%s) changed their password' % amouser)

        log.debug(u'User (%s) updated their profile' % amouser)

        amouser.save()


class BlacklistedNicknameAddForm(forms.Form):
    """Form for adding blacklisted nickname in bulk fashion."""
    nicknames = forms.CharField(widget=forms.Textarea(
        attrs={'cols': 40, 'rows': 16}))

    def clean(self):
        super(BlacklistedNicknameAddForm, self).clean()
        data = self.cleaned_data

        if 'nicknames' in data:
            data['nicknames'] = os.linesep.join(
                    [s.strip() for s in data['nicknames'].splitlines()
                        if s.strip()])
        if 'nicknames' not in data or data['nicknames'] == '':
            msg = 'Please enter at least one nickname to blacklist.'
            self._errors['nicknames'] = ErrorList([msg])

        return data
