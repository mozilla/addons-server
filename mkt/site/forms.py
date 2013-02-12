from django import forms

import commonware.log
import happyforms
from tower import ugettext as _

log = commonware.log.getLogger('z.mkt.site.forms')

APP_PUBLIC_CHOICES = (
    (0, _('As soon as it is approved.')),
    (1, _('Not until I manually make it public.')),
)


class AddonChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name


class PotatoCaptchaForm(happyforms.Form):
    # This field's value should always be blank (spammers are dumb).
    tuber = forms.CharField(required=False, label='',
        widget=forms.TextInput(attrs={'class': 'potato-captcha'}))

    # This field's value should always be 'potato' (set by JS).
    sprout = forms.CharField(required=False, label='',
        widget=forms.TextInput(attrs={'class': 'potato-captcha'}))

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')

        super(PotatoCaptchaForm, self).__init__(*args, **kwargs)

        self.has_potato_recaptcha = True
        if self.request.user.is_authenticated():
            del self.fields['tuber']
            del self.fields['sprout']
            self.has_potato_recaptcha = False

    def clean(self):
        if self.errors:
            return

        data = self.cleaned_data

        if (self.has_potato_recaptcha and
            (data.get('tuber') or data.get('sprout') != 'potato')):
            ip = self.request.META.get('REMOTE_ADDR', '')
            log.info(u'Spammer thwarted: %s' % ip)
            raise forms.ValidationError(_('Form could not be submitted.'))

        return data


class AbuseForm(PotatoCaptchaForm):
    text = forms.CharField(required=True, label='', widget=forms.Textarea)
