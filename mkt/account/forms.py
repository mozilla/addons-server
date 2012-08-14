import os
import re

from django import forms
from django.conf import settings

import commonware.log
import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from market.models import PriceCurrency
from translations.fields import TransField, TransTextarea
from users.forms import BaseAdminUserEditForm, UserRegisterForm
from users.models import UserNotification, UserProfile
import users.notifications as email
from users.tasks import resize_photo
from users.widgets import NotificationsSelectMultiple

log = commonware.log.getLogger('z.users')
admin_re = re.compile('(?=.*\d)(?=.*[a-zA-Z])')


class UserEditForm(UserRegisterForm):
    photo = forms.FileField(label=_lazy(u'Profile Photo'), required=False,
        help_text=_lazy(u'PNG and JPG supported. Large images will be resized '
                         'to fit 200 x 200 px.'))
    display_name = forms.CharField(label=_lazy(u'Display Name'), max_length=50,
        required=False,
        help_text=_lazy(u'This will be publicly displayed next to your '
                         'ratings, collections, and other contributions.'))
    notifications = forms.MultipleChoiceField(required=False, choices=[],
        widget=NotificationsSelectMultiple,
        initial=email.APP_NOTIFICATIONS_DEFAULT)
    password = forms.CharField(required=False)
    password2 = forms.CharField(required=False)
    bio = TransField(label=_lazy(u'Bio'), required=False,
                     widget=TransTextarea(attrs={'rows': 4}))

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(UserEditForm, self).__init__(*args, **kwargs)

        if self.instance:
            default = dict((i, n.default_checked) for i, n
                           in email.APP_NOTIFICATIONS_BY_ID.items())
            user = dict((n.notification_id, n.enabled) for n
                        in self.instance.notifications.all())
            default.update(user)

            # Add choices to Notification.
            choices = email.APP_NOTIFICATIONS_CHOICES
            if not self.instance.read_dev_agreement:
                choices = email.APP_NOTIFICATIONS_CHOICES_NOT_DEV

            self.fields['notifications'].choices = choices
            self.fields['notifications'].initial = [i for i, v in
                                                    default.items() if v]
            self.fields['notifications'].widget.form_instance = self

        # TODO: We should inherit from a base form not UserRegisterForm.
        if self.fields.get('recaptcha'):
            del self.fields['recaptcha']

    class Meta:
        model = UserProfile
        fields = ('username', 'display_name', 'location', 'occupation', 'bio',
                  'homepage')

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if photo:
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
            resize_photo.delay(tmp_destination, u.picture_path,
                               set_modified_on=[u])

        for i, n in email.APP_NOTIFICATIONS_BY_ID.iteritems():
            enabled = n.mandatory or (str(i) in data['notifications'])
            UserNotification.update_or_create(user=u, notification_id=i,
                update={'enabled': enabled})

        log.debug(u'User (%s) updated their profile' % u)

        u.save()
        return u


class AdminUserEditForm(BaseAdminUserEditForm, UserEditForm):
    """
    This extends from the old `AdminUserEditForm` but using our new fancy
    `UserEditForm`.
    """
    admin_log = forms.CharField(required=True, label='Reason for change',
                                widget=forms.Textarea(attrs={'rows': 4}))
    notes = forms.CharField(required=False, label='Notes',
                            widget=forms.Textarea(attrs={'rows': 4}))
    anonymize = forms.BooleanField(required=False)
    restricted = forms.BooleanField(required=False)

    def save(self, *args, **kw):
        profile = super(AdminUserEditForm, self).save()
        if self.cleaned_data['anonymize']:
            amo.log(amo.LOG.ADMIN_USER_ANONYMIZED, self.instance,
                    self.cleaned_data['admin_log'])
            profile.anonymize()  # This also logs.
        else:
            if ('restricted' in self.changed_data and
                self.cleaned_data['restricted']):
                amo.log(amo.LOG.ADMIN_USER_RESTRICTED, self.instance,
                        self.cleaned_data['admin_log'])
                profile.restrict()
            else:
                amo.log(amo.LOG.ADMIN_USER_EDITED, self.instance,
                        self.cleaned_data['admin_log'], details=self.changes())
                log.info('Admin edit user: %s changed fields: %s' %
                         (self.instance, self.changed_fields()))
        return profile


class UserDeleteForm(forms.Form):
    confirm = forms.BooleanField(
        label=_lazy(u'I understand this step cannot be undone.'))

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(UserDeleteForm, self).__init__(*args, **kwargs)

    def clean(self):
        amouser = self.request.user.get_profile()
        if amouser.is_developer:
            # This is tampering because the form isn't shown on the page if
            # the user is a developer.
            log.warning(u'[Tampering] Attempt to delete developer account (%s)'
                                                          % self.request.user)
            raise forms.ValidationError('Developers cannot delete their '
                                        'accounts.')


class CurrencyForm(happyforms.Form):
    currency = forms.ChoiceField(widget=forms.RadioSelect)

    def __init__(self, *args, **kw):
        super(CurrencyForm, self).__init__(*args, **kw)
        choices = [u'USD'] + list((PriceCurrency.objects
                                        .values_list('currency', flat=True)
                                        .distinct()))
        self.fields['currency'].choices = [(k, amo.PAYPAL_CURRENCIES[k])
                                              for k in choices if k]
