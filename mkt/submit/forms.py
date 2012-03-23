import datetime
import os

from django import forms
from django.conf import settings
from django.forms.models import modelformset_factory

import happyforms
from quieter_formset.formset import BaseModelFormSet
from tower import ugettext as _, ugettext_lazy as _lazy

from addons.forms import (AddonFormBasic, AddonFormBase, icons,
                          IconWidgetRenderer)
from addons.models import Addon, AddonUpsell, Preview
import amo
from amo.utils import raise_required, remove_icons
from apps.users.notifications import app_surveys
from apps.users.models import UserNotification
from files.models import FileUpload
from market.models import AddonPremium, Price
from mkt.developers.forms import (PaypalSetupForm as OriginalPaypalSetupForm,
                                  verify_app_domain)
from mkt.developers import tasks
from mkt.site.forms import AddonChoiceField, APP_UPSELL_CHOICES
from translations.widgets import TransInput, TransTextarea
from translations.fields import TransField


class DevAgreementForm(happyforms.Form):
    read_dev_agreement = forms.BooleanField(label=_lazy(u'Agree and Continue'),
                                            widget=forms.HiddenInput)
    newsletter = forms.BooleanField(required=False, label=app_surveys.label,
                                    widget=forms.CheckboxInput)

    def __init__(self, *args, **kw):
        self.instance = kw.pop('instance')
        super(DevAgreementForm, self).__init__(*args, **kw)

    def save(self):
        self.instance.read_dev_agreement = datetime.datetime.now()
        self.instance.save()
        if self.cleaned_data.get('newsletter'):
            UserNotification.update_or_create(user=self.instance,
                notification_id=app_surveys.id, update={'enabled': True})


class NewWebappForm(happyforms.Form):
    upload = forms.ModelChoiceField(widget=forms.HiddenInput,
        queryset=FileUpload.objects.filter(valid=True),
        error_messages={'invalid_choice': _lazy('There was an error with your '
                                                'upload. Please try again.')})

    def clean_upload(self):
        upload = self.cleaned_data['upload']
        verify_app_domain(upload.name)  # JS puts manifest URL here.
        return upload


class PaypalSetupForm(OriginalPaypalSetupForm):

    def __init__(self, *args, **kw):
        super(PaypalSetupForm, self).__init__(*args, **kw)
        self.fields['business_account'].choices = (
                ('yes', _lazy('Yes')),
                ('no', _lazy('No')),
                ('later', _lazy("I'll link my PayPal account later.")))


class PremiumTypeForm(happyforms.Form):
    premium_type = forms.TypedChoiceField(coerce=lambda x: int(x),
                                choices=amo.ADDON_PREMIUM_TYPES.items(),
                                widget=forms.RadioSelect(),
                                label=_lazy('Will your app use payments?'))


class UpsellForm(happyforms.Form):
    price = forms.ModelChoiceField(queryset=Price.objects.active(),
                                   label=_('App price'),
                                   empty_label=None,
                                   required=True)

    do_upsell = forms.TypedChoiceField(coerce=lambda x: bool(int(x)),
                                       choices=APP_UPSELL_CHOICES,
                                       widget=forms.RadioSelect(),
                                       label=_('Upsell this app'),
                                       required=False)
    free = AddonChoiceField(queryset=Addon.objects.none(),
                            required=False,
                            empty_label='',
                            label=_('App to upgrade from'),
                            widget=forms.Select())
    text = forms.CharField(widget=forms.Textarea(),
                           help_text=_('Describe the added benefits.'),
                           required=False,
                           label=_('Pitch your app'))

    def __init__(self, *args, **kw):
        self.extra = kw.pop('extra')
        self.request = kw.pop('request')
        self.addon = self.extra['addon']

        if 'initial' not in kw:
            kw['initial'] = {}

        if self.addon.premium:
            kw['initial']['price'] = self.addon.premium.price

        super(UpsellForm, self).__init__(*args, **kw)
        self.fields['free'].queryset = (self.extra['amo_user'].addons
                                    .exclude(pk=self.addon.pk)
                                    .filter(premium_type__in=amo.ADDON_FREES,
                                            status__in=amo.VALID_STATUSES,
                                            type=self.addon.type))

    def clean_text(self):
        if (self.cleaned_data['do_upsell']
            and not self.cleaned_data['text']):
            raise_required()
        return self.cleaned_data['text']

    def clean_free(self):
        if (self.cleaned_data['do_upsell']
            and not self.cleaned_data['free']):
            raise_required()
        return self.cleaned_data['free']

    def save(self):
        if 'price' in self.cleaned_data:
            premium = self.addon.premium
            if not premium:
                premium = AddonPremium()
                premium.addon = self.addon
            premium.price = self.cleaned_data['price']
            premium.save()

        upsell = self.addon.upsold
        if (self.cleaned_data['do_upsell'] and
            self.cleaned_data['text'] and self.cleaned_data['free']):

            # Check if this app was already a premium version for another app.
            if upsell and upsell.free != self.cleaned_data['free']:
                upsell.delete()

            if not upsell:
                upsell = AddonUpsell(premium=self.addon)
            upsell.text = self.cleaned_data['text']
            upsell.free = self.cleaned_data['free']
            upsell.save()
        elif not self.cleaned_data['do_upsell'] and upsell:
            upsell.delete()


class AppDetailsBasicForm(AddonFormBasic):
    """Form for "Details" submission step."""
    name = TransField(max_length=128,
                      widget=TransInput(attrs={'class': 'name l'}))
    slug = forms.CharField(max_length=30,
                           widget=forms.TextInput(attrs={'class': 'm'}))
    summary = TransField(max_length=250,
        label=_lazy(u"Provide a brief summary of your app's functionality:"),
        help_text=_lazy(u'This summary will be shown in listings and '
                         'searches.'),
        widget=TransTextarea(attrs={'rows': 2, 'class': 'full'}))
    description = TransField(required=False,
        label=_lazy(u'Provide a more detailed description of your app:'),
        help_text=_lazy(u'This description will appear on the details page.'),
        widget=TransTextarea(attrs={'rows': 4}))
    privacy_policy = TransField(widget=TransTextarea(attrs={'rows': 6}),
         label=_lazy("Please specify your app's Privacy Policy:"),
         help_text=_lazy(u"A privacy policy is required that explains what "
                          "data is transmitted from a user's computer and how "
                          "it is used."))
    homepage = TransField.adapt(forms.URLField)(required=False,
        verify_exists=False, label=_lazy(u'Homepage'),
        help_text=_(u'If your app has another homepage, enter its address '
                     'here.'),
        widget=TransInput(attrs={'class': 'full'}))
    support_url = TransField.adapt(forms.URLField)(required=False,
       verify_exists=False, label=_lazy(u'Support Website'),
       help_text=_(u'If your app has a support website or forum, enter '
                    'its address here.'),
        widget=TransInput(attrs={'class': 'full'}))
    support_email = TransField.adapt(forms.EmailField)(
        label=_lazy(u'Support Email'),
        help_text=_(u'Provide an email address for support inquiries.'),
        widget=TransInput(attrs={'class': 'full'}))

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'summary', 'tags', 'description',
                  'privacy_policy', 'homepage', 'support_url', 'support_email')


class PreviewForm(happyforms.ModelForm):
    caption = TransField(widget=TransTextarea, required=False)
    file_upload = forms.FileField(required=False)
    upload_hash = forms.CharField(required=False)
    unsaved_image_data = forms.CharField(widget=forms.HiddenInput,
                                         required=False)

    def save(self, addon, commit=True):
        if self.cleaned_data:
            self.instance.addon = addon
            if self.cleaned_data.get('DELETE'):
                # Existing preview.
                if self.instance.id:
                    self.instance.delete()
                # User has no desire to save this preview.
                return

            super(PreviewForm, self).save(commit=commit)
            if self.cleaned_data['upload_hash']:
                upload_hash = self.cleaned_data['upload_hash']
                upload_path = os.path.join(settings.TMP_PATH, 'preview',
                                           upload_hash)
                tasks.resize_preview.delay(upload_path,
                                           self.instance,
                                           set_modified_on=[self.instance])

    class Meta:
        model = Preview
        fields = ('caption', 'file_upload', 'upload_hash', 'id', 'position')


class BasePreviewFormSet(BaseModelFormSet):

    def clean(self):
        if any(self.errors):
            return
        at_least_one = False
        for i in range(0, self.total_form_count()):
            form = self.forms[i]
            if (not form.cleaned_data.get('DELETE') and
                form.cleaned_data.get('upload_hash')):
                at_least_one = True
        if not at_least_one:
            raise forms.ValidationError(_('You must upload at least one '
                                          'screen shot.'))


PreviewFormSet = modelformset_factory(Preview, formset=BasePreviewFormSet,
                                      form=PreviewForm, can_delete=True,
                                      extra=1)


class AddonFormMedia(AddonFormBase):
    icon_type = forms.CharField(widget=forms.RadioSelect(
            renderer=IconWidgetRenderer, choices=[]), required=False)
    icon_upload_hash = forms.CharField(required=False)
    unsaved_icon_data = forms.CharField(widget=forms.HiddenInput,
                                        required=False)

    class Meta:
        model = Addon
        fields = ('icon_upload_hash', 'icon_type')

    def __init__(self, *args, **kwargs):
        super(AddonFormMedia, self).__init__(*args, **kwargs)

        # Add icons here so we only read the directory when
        # AddonFormMedia is actually being used.
        self.fields['icon_type'].widget.choices = icons()

    def save(self, addon, commit=True):
        if self.cleaned_data['icon_upload_hash']:
            upload_hash = self.cleaned_data['icon_upload_hash']
            upload_path = os.path.join(settings.TMP_PATH, 'icon', upload_hash)

            dirname = addon.get_icon_dir()
            destination = os.path.join(dirname, '%s' % addon.id)

            remove_icons(destination)
            tasks.resize_icon.delay(upload_path, destination,
                                    amo.ADDON_ICON_SIZES,
                                    set_modified_on=[addon])

        return super(AddonFormMedia, self).save(commit)
