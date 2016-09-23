import os
import re

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
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
    UserProfile, UserNotification, BlacklistedName)
from .widgets import (
    NotificationsSelectMultiple, RequiredCheckboxInput, RequiredEmailInput,
    RequiredTextarea)


log = commonware.log.getLogger('z.users')
admin_re = re.compile('(?=.*\d)(?=.*[a-zA-Z])')


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


class UserRegisterForm(happyforms.ModelForm, UsernameMixin):
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
    recaptcha = ReCaptchaField()
    homepage = HttpHttpsOnlyURLField(label=_lazy(u'Homepage'), required=False)

    class Meta:
        model = UserProfile
        fields = ('username', 'display_name', 'location', 'occupation',
                  'recaptcha', 'homepage', 'email')

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

    def clean_display_name(self):
        name = self.cleaned_data['display_name']
        if BlacklistedName.blocked(name):
            raise forms.ValidationError(_('This display name cannot be used.'))
        return name


class UserEditForm(UserRegisterForm):
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
                set(['admin_log', 'notifications', 'photo']))

    def changes(self):
        """A dictionary of changed fields, old, new."""
        details = dict([(k, (self.initial[k], self.cleaned_data[k]))
                        for k in self.changed_fields()])
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
