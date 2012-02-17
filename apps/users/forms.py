import os
import re
from smtplib import SMTPException

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.contrib.auth import forms as auth_forms
from django.forms.util import ErrorList

import captcha.fields
import commonware.log
import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from amo.utils import log_cef, slug_validator
from .models import (UserProfile, UserNotification, BlacklistedUsername,
                     BlacklistedEmailDomain, BlacklistedPassword, DjangoUser)
from .widgets import NotificationsSelectMultiple
import users.notifications as email
from . import tasks

log = commonware.log.getLogger('z.users')
admin_re = re.compile('(?=.*\d)(?=.*[a-zA-Z])')


class PasswordMixin:
    min_length = 8
    error_msg = {'min_length': _('Must be %s characters or more.')
                               % min_length}

    @classmethod
    def widget(cls, **kw):
        return forms.PasswordInput(attrs={'class': 'password-strength',
                                          'data-min-length': cls.min_length},
                                   **kw)

    def clean_password(self, field='password', instance='instance'):
        data = self.cleaned_data[field]
        if not data:
            return data

        user = getattr(self, instance, None)
        if user and user.pk and user.needs_tougher_password:
            if not admin_re.search(data):
                raise forms.ValidationError(_('Letters and numbers required.'))

        if BlacklistedPassword.blocked(data):
            raise forms.ValidationError(_('That password is not allowed.'))
        return data


class AuthenticationForm(auth_forms.AuthenticationForm):
    username = forms.CharField(max_length=50)
    rememberme = forms.BooleanField(required=False)
    recaptcha = captcha.fields.ReCaptchaField()
    recaptcha_shown = forms.BooleanField(widget=forms.HiddenInput,
                                         required=False)

    def __init__(self, request=None, use_recaptcha=False, *args, **kw):
        super(AuthenticationForm, self).__init__(*args, **kw)
        if not use_recaptcha or not settings.RECAPTCHA_PRIVATE_KEY:
            del self.fields['recaptcha']


class PasswordResetForm(auth_forms.PasswordResetForm):

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(PasswordResetForm, self).__init__(*args, **kwargs)

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
            if user.needs_tougher_password:
                log_cef('Password Reset', 5, self.request,
                        username=user,
                        signature='PASSWORDRESET',
                        msg='Privileged user requested password reset')
            else:
                log_cef('Password Reset', 5, self.request,
                        username=user,
                        signature='PASSWORDRESET',
                        msg='User requested password reset')
        try:
            # Django calls send_mail() directly and has no option to pass
            # in fail_silently, so we have to catch the SMTP error ourselves
            super(PasswordResetForm, self).save(**kw)
        except SMTPException, e:
            log.error("Failed to send mail for (%s): %s" % (user, e))


class SetPasswordForm(auth_forms.SetPasswordForm, PasswordMixin):
    new_password1 = forms.CharField(label=_("New password"),
                                    min_length=PasswordMixin.min_length,
                                    error_messages=PasswordMixin.error_msg,
                                    widget=PasswordMixin.widget())

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(SetPasswordForm, self).__init__(*args, **kwargs)
        # We store our password in the users table, not auth_user like
        # Django expects.
        if isinstance(self.user, DjangoUser):
            self.user = self.user.get_profile()

    def clean_new_password1(self):
        return self.clean_password(field='new_password1', instance='user')

    def save(self, **kw):
        # Three different loggers? :(
        amo.log(amo.LOG.CHANGE_PASSWORD, user=self.user)
        log.info(u'User (%s) changed password with reset form' % self.user)
        log_cef('Password Changed', 5, self.request,
                username=self.user.username, signature='PASSWORDCHANGED',
                msg='User changed password')
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


class UsernameMixin:

    def clean_username(self):
        name = self.cleaned_data['username']
        slug_validator(name, lower=False,
            message=_('Enter a valid username consisting of letters, numbers, '
                      'underscores or hyphens.'))
        if BlacklistedUsername.blocked(name):
            raise forms.ValidationError(_('This username cannot be used.'))
        return name


class UserRegisterForm(happyforms.ModelForm, UsernameMixin, PasswordMixin):
    """
    For registering users.  We're not building off
    d.contrib.auth.forms.UserCreationForm because it doesn't do a lot of the
    details here, so we'd have to rewrite most of it anyway.
    """
    username = forms.CharField(max_length=50)
    display_name = forms.CharField(label=_lazy('Display Name'), max_length=50,
                                   required=False)
    location = forms.CharField(label=_lazy('Location'), max_length=100,
                               required=False)
    occupation = forms.CharField(label=_lazy('Occupation'), max_length=100,
                                 required=False)
    password = forms.CharField(max_length=255,
                               min_length=PasswordMixin.min_length,
                               error_messages=PasswordMixin.error_msg,
                               widget=PasswordMixin.widget(render_value=False))

    password2 = forms.CharField(max_length=255,
                                widget=forms.PasswordInput(render_value=False))
    recaptcha = captcha.fields.ReCaptchaField()

    class Meta:
        model = UserProfile
        fields = ('username', 'display_name', 'location', 'occupation',
                  'password', 'password2', 'recaptcha', 'homepage', 'email',
                  'emailhidden')

    def __init__(self, *args, **kwargs):
        super(UserRegisterForm, self).__init__(*args, **kwargs)

        if not settings.RECAPTCHA_PRIVATE_KEY:
            del self.fields['recaptcha']

        errors = {'invalid': _('This URL has an invalid format. '
                               'Valid URLs look like '
                               'http://example.com/my_page.')}
        self.fields['homepage'].error_messages = errors

    def clean_email(self):
        d = self.cleaned_data['email'].split('@')[-1]
        if BlacklistedEmailDomain.blocked(d):
            raise forms.ValidationError(_('Please use an email address from a '
                                          'different provider to complete '
                                          'your registration.'))
        return self.cleaned_data['email']

    def clean(self):
        super(UserRegisterForm, self).clean()

        data = self.cleaned_data

        # Passwords
        p1 = data.get('password')
        p2 = data.get('password2')

        # If p1 is invalid because its blocked, this message is non sensical.
        if p1 and p1 != p2:
            msg = _('The passwords did not match.')
            self._errors['password2'] = ErrorList([msg])
            if p2:
                del data['password2']

        return data


class UserEditForm(UserRegisterForm, PasswordMixin):
    oldpassword = forms.CharField(max_length=255, required=False,
                            widget=forms.PasswordInput(render_value=False))
    password = forms.CharField(max_length=255, required=False,
                               min_length=PasswordMixin.min_length,
                               error_messages=PasswordMixin.error_msg,
                               widget=PasswordMixin.widget(render_value=False))

    password2 = forms.CharField(max_length=255, required=False,
                                widget=forms.PasswordInput(render_value=False))

    photo = forms.FileField(label=_lazy(u'Profile Photo'), required=False)

    notifications = forms.MultipleChoiceField(
            choices=[],
            widget=NotificationsSelectMultiple,
            initial=email.NOTIFICATIONS_DEFAULT,
            required=False)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        self.webapp = kwargs.pop('webapp', False)
        super(UserEditForm, self).__init__(*args, **kwargs)

        if self.instance:
            default = dict((i, n.default_checked) for i, n
                           in email.NOTIFICATIONS_BY_ID.items())
            user = dict((n.notification_id, n.enabled) for n
                        in self.instance.notifications.all())
            default.update(user)

            # Add choices to Notification.
            if self.webapp:
                choices = email.APP_NOTIFICATIONS_CHOICES
                if not self.instance.is_developer:
                    choices = email.APP_NOTIFICATIONS_CHOICES_NOT_DEV
            else:
                choices = email.NOTIFICATIONS_CHOICES
                if not self.instance.is_developer:
                    choices = email.NOTIFICATIONS_CHOICES_NOT_DEV

            # Append a "NEW" message to new notification options.
            saved = self.instance.notifications.values_list('notification_id',
                                                            flat=True)
            self.choices_status = {}
            for idx, label in choices:
                self.choices_status[idx] = idx not in saved

            self.fields['notifications'].choices = choices
            self.fields['notifications'].initial = [i for i, v
                                                    in default.items() if v]
            self.fields['notifications'].widget.form_instance = self

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

    def save(self, log_for_developer=True):
        u = super(UserEditForm, self).save(commit=False)
        data = self.cleaned_data
        photo = data['photo']
        if photo:
            u.picture_type = 'image/png'
            tmp_destination = u.picture_path + '__unconverted'

            with storage.open(tmp_destination, 'wb') as fh:
                for chunk in photo.chunks():
                    fh.write(chunk)

            tasks.resize_photo.delay(tmp_destination, u.picture_path,
                                     set_modified_on=[u])

        if data['password']:
            u.set_password(data['password'])
            log_cef('Password Changed', 5, self.request, username=u.username,
                    signature='PASSWORDCHANGED', msg='User changed password')
            if log_for_developer:
                amo.log(amo.LOG.CHANGE_PASSWORD)
                log.info(u'User (%s) changed their password' % u)

        for (i, n) in email.NOTIFICATIONS_BY_ID.items():
            enabled = n.mandatory or (str(i) in data['notifications'])
            UserNotification.update_or_create(user=u, notification_id=i,
                    update={'enabled': enabled})

        log.debug(u'User (%s) updated their profile' % u)

        u.save()
        return u


class BaseAdminUserEditForm(object):

    def changed_fields(self):
        """Returns changed_data ignoring these fields."""
        return (set(self.changed_data) -
                set(['admin_log', 'notifications',
                     'password', 'password2', 'oldpassword']))

    def changes(self):
        """A dictionary of changed fields, old, new. Hides password."""
        details = dict([(k, (self.initial[k], self.cleaned_data[k]))
                           for k in self.changed_fields()])
        if 'password' in self.changed_data:
            details['password'] = ['****', '****']
        return details

    def clean_anonymize(self):
        if (self.cleaned_data['anonymize'] and
            self.changed_fields() != set(['anonymize'])):
            raise forms.ValidationError(_('To anonymize, enter a reason for'
                                          ' the change but do not change any'
                                          ' other field.'))
        return self.cleaned_data['anonymize']


class AdminUserEditForm(BaseAdminUserEditForm, UserEditForm):
    """This is the form used by admins to edit users' info."""
    admin_log = forms.CharField(required=True, label='Reason for change',
                                widget=forms.Textarea(attrs={'rows': 4}))
    confirmationcode = forms.CharField(required=False, max_length=255,
                                       label='Confirmation code')
    notes = forms.CharField(required=False, label='Notes',
                            widget=forms.Textarea(attrs={'rows': 4}))
    anonymize = forms.BooleanField(required=False)

    def save(self, *args, **kw):
        profile = super(AdminUserEditForm, self).save(log_for_developer=False)
        if self.cleaned_data['anonymize']:
            amo.log(amo.LOG.ADMIN_USER_ANONYMIZED, self.instance,
                    self.cleaned_data['admin_log'])
            profile.anonymize()  # This also logs
        else:
            amo.log(amo.LOG.ADMIN_USER_EDITED, self.instance,
                    self.cleaned_data['admin_log'], details=self.changes())
            log.info('Admin edit user: %s changed fields: %s' %
                     (self.instance, self.changed_fields()))
            if 'password' in self.changes():
                log_cef('Password Changed', 5, self.request,
                        username=self.instance.username,
                        signature='PASSWORDRESET',
                        msg='Admin requested password reset',
                        cs1=self.request.amo_user.username,
                        cs1Label='AdminName')
        return profile


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


class ContactForm(happyforms.Form):
    text = forms.CharField(widget=forms.Textarea())


class RemoveForm(happyforms.Form):
    remove = forms.BooleanField()
