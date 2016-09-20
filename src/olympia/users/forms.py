import os
import re
from smtplib import SMTPException

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.contrib.auth import forms as auth_forms
from django.contrib.auth.tokens import default_token_generator
from django.forms.util import ErrorList
from django.utils.translation import ugettext as _, ugettext_lazy as _lazy

import commonware.log

from olympia import amo
from olympia.accounts.views import fxa_error_message
from olympia.amo.fields import ReCaptchaField, HttpHttpsOnlyURLField
from olympia.users import notifications as email
from olympia.amo.utils import clean_nl, has_links, slug_validator
from olympia.lib import happyforms
from olympia.translations import LOCALES

from . import tasks
from .models import (
    UserProfile, UserNotification, BlacklistedName, BlacklistedEmailDomain)
from .widgets import (
    NotificationsSelectMultiple, RequiredCheckboxInput, RequiredEmailInput,
    RequiredInputMixin, RequiredTextarea)


log = commonware.log.getLogger('z.users')
admin_re = re.compile('(?=.*\d)(?=.*[a-zA-Z])')


class PasswordMixin:
    min_length = 8
    error_msg = {
        'min_length': _lazy('Must be %s characters or more.') % min_length}

    @classmethod
    def widget(cls, **kw):
        attrs = {
            'class': 'password-strength',
            'data-min-length': cls.min_length,
        }
        if kw.pop('required', False):
            attrs.update(RequiredInputMixin.required_attrs)
        return forms.PasswordInput(attrs=attrs, **kw)

    def clean_password(self, field='password', instance='instance'):
        data = self.cleaned_data[field]
        if not data:
            return data

        user = getattr(self, instance, None)
        if user and user.pk and user.needs_tougher_password:
            if not admin_re.search(data):
                raise forms.ValidationError(_('Letters and numbers required.'))
        return data


class PasswordResetForm(auth_forms.PasswordResetForm):
    email = forms.EmailField(widget=RequiredEmailInput)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(PasswordResetForm, self).__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data['email']
        self.users_cache = UserProfile.objects.filter(email__iexact=email)
        try:
            if self.users_cache.get().fxa_migrated():
                raise forms.ValidationError(
                    _('You must recover your password through Firefox '
                      'Accounts. Try logging in instead.'))
        except UserProfile.DoesNotExist:
            pass
        return email

    def save(self, **kw):
        if not self.users_cache:
            log.info("Unknown email used for password reset: {email}".format(
                **self.cleaned_data))
            return
        for user in self.users_cache:
            if user.needs_tougher_password:
                log.info(
                    u'Password reset email sent for privileged user (%s)'
                    % user)
            else:
                log.info(
                    u'Password reset email sent for user (%s)'
                    % user)
        try:
            # Django calls send_mail() directly and has no option to pass
            # in fail_silently, so we have to catch the SMTP error ourselves
            self.base_save(**kw)
        except SMTPException, e:
            log.error("Failed to send mail for (%s): %s" % (user, e))

    # Copypaste from superclass
    def base_save(
            self, domain_override=None,
            subject_template_name='registration/password_reset_subject.txt',
            email_template_name='registration/password_reset_email.html',
            use_https=False, token_generator=default_token_generator,
            from_email=None, request=None, html_email_template_name=None):
        """
        Generates a one-use only link for resetting password and sends to the
        user.
        """
        from django.core.mail import send_mail
        from django.contrib.auth import get_user_model
        from django.contrib.sites.models import get_current_site
        from django.template import loader
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        UserModel = get_user_model()
        email = self.cleaned_data["email"]
        active_users = UserModel._default_manager.filter(
            email__iexact=email,
            # we use "deleted" instead of "is_active"
            deleted=False)

        for user in active_users:
            # Make sure that no email is sent to a user that actually has
            # a password marked as unusable
            if not user.has_usable_password():
                continue
            if not domain_override:
                current_site = get_current_site(request)
                site_name = current_site.name
                domain = current_site.domain
            else:
                site_name = domain = domain_override
            c = {
                'email': user.email,
                'domain': domain,
                'site_name': site_name,
                'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                'user': user,
                'token': token_generator.make_token(user),
                'protocol': 'https' if use_https else 'http',
            }
            subject = loader.render_to_string(subject_template_name, c)
            # Email subject *must not* contain newlines
            subject = ''.join(subject.splitlines())
            email = loader.render_to_string(email_template_name, c)

            if html_email_template_name:
                html_email = loader.render_to_string(
                    html_email_template_name, c)
            else:
                html_email = None
            send_mail(
                subject, email, from_email, [user.email],
                html_message=html_email)


class SetPasswordForm(auth_forms.SetPasswordForm, PasswordMixin):
    new_password1 = forms.CharField(label=_lazy(u'New password'),
                                    min_length=PasswordMixin.min_length,
                                    error_messages=PasswordMixin.error_msg,
                                    widget=PasswordMixin.widget(required=True))

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(SetPasswordForm, self).__init__(*args, **kwargs)

    def clean_new_password1(self):
        return self.clean_password(field='new_password1', instance='user')

    def save(self, **kw):
        # Three different loggers? :(
        amo.log(amo.LOG.CHANGE_PASSWORD, user=self.user)
        log.info(u'User (%s) changed password with reset form' % self.user)
        super(SetPasswordForm, self).save(**kw)


class UserDeleteForm(forms.Form):
    email = forms.CharField(max_length=255, required=True,
                            widget=RequiredEmailInput)
    confirm = forms.BooleanField(required=True, widget=RequiredCheckboxInput)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(UserDeleteForm, self).__init__(*args, **kwargs)
        self.fields['email'].widget.attrs['placeholder'] = (
            self.request.user.email)

    def clean_email(self):
        user_email = self.request.user.email
        if not user_email == self.cleaned_data['email']:
            raise forms.ValidationError(_('Email must be {email}.').format(
                email=user_email))

    def clean(self):
        amouser = self.request.user
        if amouser.is_developer:
            # This is tampering because the form isn't shown on the page if the
            # user is a developer
            log.warning(u'[Tampering] Attempt to delete developer account (%s)'
                        % self.request.user)
            raise forms.ValidationError("")


class UsernameMixin:

    def clean_username(self):
        name = self.cleaned_data['username']

        if not name:
            if self.instance.has_anonymous_username():
                name = self.instance.username
            else:
                name = self.instance.anonymize_username()

        # All-digits usernames are disallowed since they can be
        # confused for user IDs in URLs. (See bug 862121.)
        if name.isdigit():
            raise forms.ValidationError(
                _('Usernames cannot contain only digits.'))

        slug_validator(
            name, lower=False,
            message=_('Enter a valid username consisting of letters, numbers, '
                      'underscores or hyphens.'))
        if BlacklistedName.blocked(name):
            raise forms.ValidationError(_('This username cannot be used.'))

        # FIXME: Bug 858452. Remove this check when collation of the username
        # column is changed to case insensitive.
        if (UserProfile.objects.exclude(id=self.instance.id)
                       .filter(username__iexact=name).exists()):
            raise forms.ValidationError(_('This username is already in use.'))

        return name


class UserRegisterForm(happyforms.ModelForm, UsernameMixin, PasswordMixin):
    """
    For registering users.  We're not building off
    d.contrib.auth.forms.UserCreationForm because it doesn't do a lot of the
    details here, so we'd have to rewrite most of it anyway.
    """
    username = forms.CharField(max_length=50, required=False)
    email = forms.EmailField(widget=RequiredEmailInput)
    display_name = forms.CharField(label=_lazy(u'Display Name'), max_length=50,
                                   required=False)
    location = forms.CharField(label=_lazy(u'Location'), max_length=100,
                               required=False)
    occupation = forms.CharField(label=_lazy(u'Occupation'), max_length=100,
                                 required=False)
    password = forms.CharField(max_length=255,
                               min_length=PasswordMixin.min_length,
                               error_messages=PasswordMixin.error_msg,
                               widget=PasswordMixin.widget(render_value=False,
                                                           required=True))
    password2 = forms.CharField(max_length=255,
                                widget=PasswordMixin.widget(render_value=False,
                                                            required=True))
    recaptcha = ReCaptchaField()
    homepage = HttpHttpsOnlyURLField(label=_lazy(u'Homepage'), required=False)

    class Meta:
        model = UserProfile
        fields = ('username', 'display_name', 'location', 'occupation',
                  'password', 'password2', 'recaptcha', 'homepage', 'email')

    def __init__(self, *args, **kwargs):
        instance = kwargs.get('instance')
        if instance and instance.has_anonymous_username():
            kwargs.setdefault('initial', {})
            kwargs['initial']['username'] = ''

        super(UserRegisterForm, self).__init__(*args, **kwargs)

        if not settings.NOBOT_RECAPTCHA_PRIVATE_KEY:
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

    def clean_display_name(self):
        name = self.cleaned_data['display_name']
        if BlacklistedName.blocked(name):
            raise forms.ValidationError(_('This display name cannot be used.'))
        return name

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
    oldpassword = forms.CharField(
        max_length=255, required=False,
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

    lang = forms.TypedChoiceField(label=_lazy(u'Default locale'),
                                  choices=LOCALES)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(UserEditForm, self).__init__(*args, **kwargs)

        if not self.instance.lang and self.request:
            self.initial['lang'] = self.request.LANG

        if self.instance:
            default = dict((i, n.default_checked) for i, n
                           in email.NOTIFICATIONS_BY_ID.items())
            user = dict((n.notification_id, n.enabled) for n
                        in self.instance.notifications.all())
            default.update(user)

            # Add choices to Notification.
            choices = email.NOTIFICATIONS_CHOICES
            if not self.instance.is_developer:
                choices = email.NOTIFICATIONS_CHOICES_NOT_DEV

            if self.instance.fxa_migrated():
                self.fields['email'].required = False
                self.fields['email'].widget = forms.EmailInput(
                    attrs={'readonly': 'readonly'})
                self.fields['email'].help_text = fxa_error_message(
                    _(u'Firefox Accounts users cannot currently change their '
                      u'email address.'))

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
        exclude = ('password', 'picture_type', 'last_login', 'fxa_id',
                   'read_dev_agreement')

    def clean(self):
        data = self.cleaned_data
        amouser = self.request.user

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

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if self.instance.fxa_migrated():
            if not email or email == self.instance.email:
                return self.instance.email
            else:
                raise forms.ValidationError(_(u'Email cannot be changed.'))
        else:
            return email

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

    def clean_bio(self):
        bio = self.cleaned_data['bio']
        normalized = clean_nl(unicode(bio))
        if has_links(normalized):
            # There's some links, we don't want them.
            raise forms.ValidationError(_('No links are allowed.'))
        return bio

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
            log.info(u'User (%s) changed their password' % u.username)
            if log_for_developer:
                amo.log(amo.LOG.CHANGE_PASSWORD)

        for (i, n) in email.NOTIFICATIONS_BY_ID.items():
            enabled = n.mandatory or (str(i) in data['notifications'])
            UserNotification.update_or_create(
                user=u, notification_id=i, update={'enabled': enabled})

        log.debug(u'User (%s) updated their profile' % u)

        u.save()
        return u


class BaseAdminUserEditForm(object):

    def changed_fields(self):
        """Returns changed_data ignoring these fields."""
        return (set(self.changed_data) -
                set(['admin_log', 'notifications', 'photo',
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
                                widget=RequiredTextarea(attrs={'rows': 4}))
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
                log.info(
                    'admin requested password reset (%s for %s)'
                    % (self.request.user.username, self.instance.username))
        return profile


class BlacklistedNameAddForm(forms.Form):
    """Form for adding blacklisted names in bulk fashion."""
    names = forms.CharField(widget=forms.Textarea(
        attrs={'cols': 40, 'rows': 16}))

    def clean_names(self):
        names = self.cleaned_data['names'].strip()
        if not names:
            raise forms.ValidationError(
                _('Please enter at least one name to blacklist.'))
        names = os.linesep.join(
            [s.strip() for s in names.splitlines() if s.strip()])
        return names


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
