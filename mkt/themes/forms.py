from datetime import datetime
import os

from django import forms
from django.conf import settings
from django.core.urlresolvers import reverse

from tower import ugettext_lazy as _lazy

import amo
from amo.fields import ColorField
from addons.forms import AddonFormBase, clean_name
from addons.models import Addon, AddonCategory, AddonUser, Category, Persona
from versions.models import Version


class NewThemeForm(AddonFormBase):
    name = forms.CharField(max_length=50)
    category = forms.ModelChoiceField(queryset=Category.objects.all(),
        widget=forms.widgets.RadioSelect,
        label=_lazy('Select the category that best describes your Theme.'))
    slug = forms.CharField(max_length=30, widget=forms.TextInput)
    summary = forms.CharField(widget=forms.widgets.Textarea(attrs={'rows': 4}),
                        label=_lazy('Describe your Theme.'),
                        max_length=250, required=False)
    license = forms.TypedChoiceField(choices=amo.PERSONA_LICENSES_IDS,
        coerce=int, empty_value=None, widget=forms.HiddenInput,
        error_messages={'required': _lazy(u'A license must be selected.')})
    header = forms.FileField(required=False)
    header_hash = forms.CharField(widget=forms.HiddenInput)
    footer = forms.FileField(required=False)
    footer_hash = forms.CharField(widget=forms.HiddenInput)
    accentcolor = ColorField(required=False)
    textcolor = ColorField(required=False)
    # This lets us POST the data URIs of the unsaved previews so we can still
    # show them if there were form errors. It's really clever.
    unsaved_data = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Addon
        fields = ('name', 'summary')

    def __init__(self, *args, **kwargs):
        super(NewThemeForm, self).__init__(*args, **kwargs)
        cats = Category.objects.filter(application=amo.FIREFOX.id,
                                       type=amo.ADDON_PERSONA, weight__gte=0)
        cats = sorted(cats, key=lambda x: x.name)
        self.fields['category'].choices = [(c.id, c.name) for c in cats]

        widgetAttrs = self.fields['header'].widget.attrs
        widgetAttrs['data-upload-url'] = reverse(
            'submit.theme.upload', args=['persona_header'])
        widgetAttrs['data-allowed-types'] = 'image/jpeg|image/png'

        widgetAttrs = self.fields['footer'].widget.attrs
        widgetAttrs['data-upload-url'] = reverse(
            'submit.theme.upload', args=['persona_footer'])
        widgetAttrs['data-allowed-types'] = 'image/jpeg|image/png'

    def clean_name(self):
        return clean_name(self.cleaned_data['name'])

    def save(self, commit=False):
        from addons.tasks import (create_persona_preview_image,
                                  save_persona_image)
        data = self.cleaned_data
        addon = Addon.objects.create(id=None, name=data['name'],
            slug=data['slug'], description=data['summary'],
            status=amo.STATUS_PENDING, type=amo.ADDON_PERSONA)
        addon._current_version = Version.objects.create(addon=addon,
                                                        version='0')
        addon.save()

        # Save header, footer, and preview images.
        try:
            header = data['header_hash']
            footer = data['footer_hash']
            header = os.path.join(settings.TMP_PATH, 'persona_header', header)
            footer = os.path.join(settings.TMP_PATH, 'persona_footer', footer)
            dst_root = os.path.join(settings.PERSONAS_PATH, str(addon.id))

            save_persona_image.delay(src=header,
                full_dst=os.path.join(dst_root, 'header.png'))
            save_persona_image.delay(src=footer,
                full_dst=os.path.join(dst_root, 'footer.png'))
            create_persona_preview_image.delay(src=header,
                full_dst=os.path.join(dst_root, 'preview.png'),
                set_modified_on=[addon])
        except IOError:
            addon.delete()
            raise IOError

        # Save user info.
        user = self.request.amo_user
        AddonUser(addon=addon, user=user).save()

        # Create Persona instance.
        p = Persona()
        p.persona_id = 0
        p.addon = addon
        p.header = 'header'
        p.footer = 'footer'
        if data['accentcolor']:
            p.accentcolor = data['accentcolor'].lstrip('#')
        if data['textcolor']:
            p.textcolor = data['textcolor'].lstrip('#')
        p.license_id = data['license']
        p.submit = datetime.now()
        p.author = user.name
        p.display_username = user.username
        p.save()

        # Save categories.
        tb_c, created = Category.objects.get_or_create(
            application_id=amo.THUNDERBIRD.id,
            name__id=data['category'].name.id, type=amo.ADDON_PERSONA)
        AddonCategory(addon=addon, category=data['category']).save()
        AddonCategory(addon=addon, category=tb_c).save()

        return addon
