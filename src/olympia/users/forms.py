import os
import re

import waffle

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.utils.translation import ugettext, ugettext_lazy as _

import olympia.core.logger

from olympia import amo
from olympia.accounts.views import fxa_error_message
from olympia.activity.models import ActivityLog
from olympia.amo.fields import HttpHttpsOnlyURLField
from olympia.amo.utils import (
    clean_nl, has_links, ImageCheck, slug_validator,
    fetch_subscribed_newsletters, subscribe_newsletter,
    unsubscribe_newsletter)
from olympia.lib import happyforms
from olympia.users import notifications

from . import tasks
from .models import DeniedName, UserNotification, UserProfile
from .widgets import (
    NotificationsSelectMultiple, RequiredCheckboxInput, RequiredEmailInput,
    RequiredTextarea)


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
            raise forms.ValidationError(
                ugettext('Email must be {email}.').format(email=user_email))

    def clean(self):
        amouser = self.request.user
        if amouser.is_developer:
            # This is tampering because the form isn't shown on the page if the
            # user is a developer
            log.warning(u'[Tampering] Attempt to delete developer account (%s)'
                        % self.request.user)
            raise forms.ValidationError("")


LOGIN_HELP_URL = (
    'https://support.mozilla.org/kb/'
    'change-primary-email-address-firefox-accounts')


class UserEditForm(happyforms.ModelForm):
    username = forms.CharField(max_length=50, required=False)
    display_name = forms.CharField(label=_(u'Display Name'), max_length=50,
                                   required=False)
    location = forms.CharField(label=_(u'Location'), max_length=100,
                               required=False)
    occupation = forms.CharField(label=_(u'Occupation'), max_length=100,
                                 required=False)
    homepage = HttpHttpsOnlyURLField(label=_(u'Homepage'), required=False)
    email = forms.EmailField(
        required=False,
        help_text=fxa_error_message(
            _(u'You can change your email address on Firefox Accounts.'),
            LOGIN_HELP_URL),
        widget=forms.EmailInput(attrs={'readonly': 'readonly'}))
    photo = forms.FileField(label=_(u'Profile Photo'), required=False)
    biography = forms.CharField(widget=forms.Textarea, required=False)

    notifications = forms.MultipleChoiceField(
        choices=[],
        widget=NotificationsSelectMultiple,
        initial=notifications.NOTIFICATIONS_DEFAULT,
        required=False)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)

        instance = kwargs.get('instance')
        if instance and instance.has_anonymous_username:
            kwargs.setdefault('initial', {})
            kwargs['initial']['username'] = ''

        super(UserEditForm, self).__init__(*args, **kwargs)

        errors = {
            'invalid': ugettext(
                'This URL has an invalid format. Valid URLs look like '
                'http://example.com/my_page.')}
        self.fields['homepage'].error_messages = errors

        if self.instance:
            # We are fetching all `UserNotification` instances and then,
            # if the waffle-switch is active overwrite their value with the
            # data from basket. This simplifies the process of implementing
            # the waffle-switch. Once we switched the integration "on" on prod
            # all `UserNotification` instances that are now handled by basket
            # can be deleted.
            default = {
                idx: notification.default_checked
                for idx, notification
                in notifications.NOTIFICATIONS_BY_ID.items()}
            user = {
                notification.notification_id: notification.enabled
                for notification in self.instance.notifications.all()}
            default.update(user)

            if waffle.switch_is_active('activate-basket-sync'):
                newsletters = fetch_subscribed_newsletters(self.instance)

                by_basket_id = notifications.REMOTE_NOTIFICATIONS_BY_BASKET_ID
                for basket_id, notification in by_basket_id.items():
                    default[notification.id] = basket_id in newsletters

            # Add choices to Notification.
            if self.instance.is_developer:
                choices = [
                    (l.id, l.label)
                    for l in notifications.NOTIFICATIONS_COMBINED]
            else:
                choices = [
                    (l.id, l.label)
                    for l in notifications.NOTIFICATIONS_COMBINED
                    if l.group != 'dev']

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

    class Meta:
        model = UserProfile
        fields = (
            'username', 'email', 'display_name', 'location', 'occupation',
            'homepage', 'photo', 'biography', 'display_collections',
            'display_collections_fav', 'notifications',
        )

    def clean_username(self):
        name = self.cleaned_data['username']

        if not name:
            if self.instance.has_anonymous_username:
                name = self.instance.username
            else:
                name = self.instance.anonymize_username()

        # All-digits usernames are disallowed since they can be
        # confused for user IDs in URLs. (See bug 862121.)
        if name.isdigit():
            raise forms.ValidationError(
                ugettext('Usernames cannot contain only digits.'))

        slug_validator(
            name, lower=False,
            message=ugettext(
                'Enter a valid username consisting of letters, numbers, '
                'underscores or hyphens.'))
        if DeniedName.blocked(name):
            raise forms.ValidationError(
                ugettext('This username cannot be used.'))

        # FIXME: Bug 858452. Remove this check when collation of the username
        # column is changed to case insensitive.
        if (UserProfile.objects.exclude(id=self.instance.id)
                       .filter(username__iexact=name).exists()):
            raise forms.ValidationError(
                ugettext('This username is already in use.'))

        return name

    def clean_display_name(self):
        name = self.cleaned_data['display_name']
        if DeniedName.blocked(name):
            raise forms.ValidationError(
                ugettext('This display name cannot be used.'))
        return name

    def clean_email(self):
        # TODO(django 1.9): Change the field to disabled=True and remove this.
        return self.instance.email

    def clean_photo(self):
        photo = self.cleaned_data['photo']

        if not photo:
            return

        image_check = ImageCheck(photo)
        if (photo.content_type not in amo.IMG_TYPES or
                not image_check.is_image()):
            raise forms.ValidationError(
                ugettext('Images must be either PNG or JPG.'))

        if image_check.is_animated():
            raise forms.ValidationError(ugettext('Images cannot be animated.'))

        if photo.size > settings.MAX_PHOTO_UPLOAD_SIZE:
            msg = ugettext('Please use images smaller than %dMB.')
            size_in_mb = settings.MAX_PHOTO_UPLOAD_SIZE / 1024 / 1024
            raise forms.ValidationError(msg % size_in_mb)

        return photo

    def clean_biography(self):
        biography = self.cleaned_data['biography']
        normalized = clean_nl(unicode(biography))
        if has_links(normalized):
            # There's some links, we don't want them.
            raise forms.ValidationError(ugettext('No links are allowed.'))
        return biography

    def save(self, log_for_developer=True):
        user = super(UserEditForm, self).save(commit=False)
        data = self.cleaned_data
        photo = data['photo']
        if photo:
            user.picture_type = 'image/png'
            tmp_destination = user.picture_path_original

            with storage.open(tmp_destination, 'wb') as fh:
                for chunk in photo.chunks():
                    fh.write(chunk)

            tasks.resize_photo.delay(
                tmp_destination, user.picture_path,
                set_modified_on=user.serializable_reference())

        visible_notifications = (
            notifications.NOTIFICATIONS_BY_ID if self.instance.is_developer
            else notifications.NOTIFICATIONS_BY_ID_NOT_DEV)

        for (notification_id, notification) in visible_notifications.items():
            enabled = (notification.mandatory or
                       (str(notification_id) in data['notifications']))
            UserNotification.objects.update_or_create(
                user=self.instance, notification_id=notification_id,
                defaults={'enabled': enabled})

        if waffle.switch_is_active('activate-basket-sync'):
            by_basket_id = notifications.REMOTE_NOTIFICATIONS_BY_BASKET_ID
            for basket_id, notification in by_basket_id.items():
                needs_subscribe = str(notification.id) in data['notifications']
                needs_unsubscribe = (
                    str(notification.id) not in data['notifications'])

                if needs_subscribe:
                    subscribe_newsletter(
                        self.instance, basket_id, request=self.request)
                elif needs_unsubscribe:
                    unsubscribe_newsletter(self.instance, basket_id)

        log.debug(u'User (%s) updated their profile' % user)

        user.save()
        return user


class AdminUserEditForm(UserEditForm):
    """This is the form used by admins to edit users' info."""
    email = forms.EmailField(widget=RequiredEmailInput)
    admin_log = forms.CharField(required=True, label='Reason for change',
                                widget=RequiredTextarea(attrs={'rows': 4}))
    notes = forms.CharField(required=False, label='Notes',
                            widget=forms.Textarea(attrs={'rows': 4}))
    anonymize = forms.BooleanField(required=False)

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
            raise forms.ValidationError(ugettext(
                'To anonymize, enter a reason for the change but do not '
                'change any other field.'))
        return self.cleaned_data['anonymize']

    def clean_email(self):
        return self.cleaned_data['email']

    def save(self, *args, **kw):
        profile = super(AdminUserEditForm, self).save(log_for_developer=False)
        if self.cleaned_data['anonymize']:
            ActivityLog.create(amo.LOG.ADMIN_USER_ANONYMIZED, self.instance,
                               self.cleaned_data['admin_log'])
            profile.delete()  # This also logs
        else:
            ActivityLog.create(amo.LOG.ADMIN_USER_EDITED, self.instance,
                               self.cleaned_data['admin_log'],
                               details=self.changes())
            log.info('Admin edit user: %s changed fields: %s' %
                     (self.instance, self.changed_fields()))
        return profile


class DeniedNameAddForm(forms.Form):
    """Form for adding denied names in bulk fashion."""
    names = forms.CharField(widget=forms.Textarea(
        attrs={'cols': 40, 'rows': 16}))

    def clean_names(self):
        names = self.cleaned_data['names'].strip()
        if not names:
            raise forms.ValidationError(
                ugettext('Please enter at least one name to be denied.'))
        names = os.linesep.join(
            [s.strip() for s in names.splitlines() if s.strip()])
        return names
