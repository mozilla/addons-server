import os
from smtplib import SMTPException

from django import forms
from django.conf import settings
from django.contrib.auth import forms as auth_forms
from django.forms.util import ErrorList

import captcha.fields
import commonware.log
import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy

from amo.utils import slug_validator
from .models import (UserProfile, BlacklistedUsername, BlacklistedEmailDomain,
                     DjangoUser)
from . import tasks

log = commonware.log.getLogger('z.users')


class AuthenticationForm(auth_forms.AuthenticationForm):
    rememberme = forms.BooleanField(required=False)


class PasswordResetForm(auth_forms.PasswordResetForm):

    def clean_email(self):
        email = self.cleaned_data['email']
        self.users_cache = UserProfile.objects.filter(email__iexact=email)
        if not self.users_cache:
            raise forms.ValidationError(
                _("""An email has been sent to the requested account with
                  further information. If you do not receive an email then
                  please confirm you have entered the same email address used
                  during account registration."""))
        return email

    def save(self, **kw):
        for user in self.users_cache:
            log.info(u'Password reset email sent for user (%s)' % user)
        try:
            # Django calls send_mail() directly and has no option to pass
            # in fail_silently, so we have to catch the SMTP error ourselves
            super(PasswordResetForm, self).save(**kw)
        except SMTPException, e:
            log.error("Failed to send mail for (%s): %s" % (user, e))


class SetPasswordForm(auth_forms.SetPasswordForm):

    def __init__(self, *args, **kwargs):
        super(SetPasswordForm, self).__init__(*args, **kwargs)
        # We store our password in the users table, not auth_user like
        # Django expects.
        if isinstance(self.user, DjangoUser):
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


class UserRegisterForm(happyforms.ModelForm):
    """
    For registering users.  We're not building off
    d.contrib.auth.forms.UserCreationForm because it doesn't do a lot of the
    details here, so we'd have to rewrite most of it anyway.
    """

    password = forms.CharField(max_length=255,
                               widget=forms.PasswordInput(render_value=False))

    password2 = forms.CharField(max_length=255,
                                widget=forms.PasswordInput(render_value=False))
    recaptcha = captcha.fields.ReCaptchaField()

    class Meta:
        model = UserProfile

    def __init__(self, *args, **kwargs):
        super(UserRegisterForm, self).__init__(*args, **kwargs)

        if not settings.RECAPTCHA_PRIVATE_KEY:
            del self.fields['recaptcha']

    def clean_email(self):
        d = self.cleaned_data['email'].split('@')[-1]
        if BlacklistedEmailDomain.blocked(d):
            raise forms.ValidationError(_('Please use an email address from a '
                                          'different provider to complete '
                                          'your registration.'))
        return self.cleaned_data['email']

    def clean_username(self):
        name = self.cleaned_data['username']
        slug_validator(name, lower=False)
        if BlacklistedUsername.blocked(name):
            raise forms.ValidationError(_('This username is invalid.'))
        return name

    def clean(self):
        super(UserRegisterForm, self).clean()

        data = self.cleaned_data

        # Passwords
        p1 = data.get('password')
        p2 = data.get('password2')

        if p1 != p2:
            msg = _('The passwords did not match.')
            self._errors['password2'] = ErrorList([msg])
            if p2:
                del data['password2']

        return data


class UserEditForm(UserRegisterForm):
    oldpassword = forms.CharField(max_length=255, required=False,
                            widget=forms.PasswordInput(render_value=False))
    password = forms.CharField(max_length=255, required=False,
                               widget=forms.PasswordInput(render_value=False))

    password2 = forms.CharField(max_length=255, required=False,
                                widget=forms.PasswordInput(render_value=False))

    photo = forms.FileField(label=_lazy('Profile Photo'), required=False)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(UserEditForm, self).__init__(*args, **kwargs)

        # TODO: We should inherit from a base form not UserRegisterForm
        if self.fields.get('recaptcha'):
            del self.fields['recaptcha']

    class Meta:
        model = UserProfile
        exclude = ('password', 'picture_type')

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

    def clean_photo(self):
        photo = self.cleaned_data['photo']

        if not photo:
            return

        if photo.content_type not in ('image/png', 'image/jpeg'):
            raise forms.ValidationError(
                    _('Images must be either PNG or JPG.'))

        if photo.size > settings.MAX_PHOTO_UPLOAD_SIZE:
            raise forms.ValidationError(
                    _('Please use images smaller than %dMB.' %
                      (settings.MAX_PHOTO_UPLOAD_SIZE / 1024 / 1024 - 1)))

        return photo

    def save(self):
        u = super(UserEditForm, self).save(commit=False)
        data = self.cleaned_data
        photo = data['photo']
        if photo:
            u.picture_type = 'image/png'
            tmp_destination = u.picture_path + '__unconverted'

            if not os.path.exists(u.picture_dir):
                os.makedirs(u.picture_dir)

            fh = open(tmp_destination, 'w')
            for chunk in photo.chunks():
                fh.write(chunk)

            fh.close()
            tasks.resize_photo.delay(tmp_destination, u.picture_path)

        if data['password']:
            u.set_password(data['password'])
            log.info(u'User (%s) changed their password' % u)

        log.debug(u'User (%s) updated their profile' % u)

        u.save()
        return u


class BlacklistedUsernameAddForm(forms.Form):
    """Form for adding blacklisted username in bulk fashion."""
    usernames = forms.CharField(widget=forms.Textarea(
        attrs={'cols': 40, 'rows': 16}))

    def clean(self):
        super(BlacklistedUsernameAddForm, self).clean()
        data = self.cleaned_data

        if 'usernames' in data:
            data['usernames'] = os.linesep.join(
                    [s.strip() for s in data['usernames'].splitlines()
                        if s.strip()])
        if 'usernames' not in data or data['usernames'] == '':
            msg = 'Please enter at least one username to blacklist.'
            self._errors['usernames'] = ErrorList([msg])

        return data


class BlacklistedEmailDomainAddForm(forms.Form):
    """Form for adding blacklisted user e-mail domains in bulk fashion."""
    domains = forms.CharField(
            widget=forms.Textarea(attrs={'cols': 40, 'rows': 16}))

    def clean(self):
        super(BlacklistedEmailDomainAddForm, self).clean()
        data = self.cleaned_data

        if 'domains' in data:
            l = filter(None, [s.strip() for s in data['domains'].splitlines()])
            data['domains'] = os.linesep.join(l)

        if not data.get('domains', ''):
            msg = 'Please enter at least one e-mail domain to blacklist.'
            self._errors['domains'] = ErrorList([msg])

        return data
