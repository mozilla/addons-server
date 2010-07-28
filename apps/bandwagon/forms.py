import os

from django import forms
from django.conf import settings

import commonware
from tower import ugettext as _

from addons.models import Addon
from .models import Collection, CollectionAddon
# TODO(davedash) uncomment after PIL
# from . import tasks

privacy_choices = (
        (False, _('Only I can view this collection.')),
        (True, _('Anybody can view this collection.')))

log = commonware.log.getLogger('z.image')


class CollectionForm(forms.ModelForm):

    name = forms.CharField(max_length=100,
                           label=_('Give your collection a name.'))
    slug = forms.CharField(label=_('URL:'))
    description = forms.CharField(label=_('Describe your collections.'),
                                  widget=forms.Textarea, required=False)
    listed = forms.ChoiceField(
            label=_('Who can view your collection?'),
            widget=forms.RadioSelect,
            choices=privacy_choices,
            initial=True,
            )

    icon = forms.FileField(label=_('Give your collection an icon.'),
                           required=False)

    addon = forms.CharField(widget=forms.MultipleHiddenInput, required=False)
    addon_comment = forms.CharField(widget=forms.MultipleHiddenInput,
                                     required=False)

    def clean_addon(self):
        addon_ids = self.data.getlist('addon')
        return Addon.objects.filter(pk__in=addon_ids)

    def clean_addon_comment(self):
        addon_ids = self.data.getlist('addon')
        return dict(zip(map(int, addon_ids),
                        self.data.getlist('addon_comment')))

    def clean_description(self):
        description = self.cleaned_data['description']
        if description.strip() == '':
            description = None

        return description

    def clean_slug(self):
        author = self.initial['author']
        slug = self.cleaned_data['slug']

        if author.collections.filter(slug=slug).count():
            raise forms.ValidationError(
                    _('This url is already in use by another collection'))

        return slug

    def clean_icon(self):
        icon = self.cleaned_data['icon']
        if not icon:
            return
        if icon.content_type not in ('image/png', 'image/jpeg'):
            raise forms.ValidationError(
                    _('Icons must be either PNG or JPG.'))

        if icon.size > settings.MAX_ICON_UPLOAD_SIZE:
            raise forms.ValidationError(
                    _('Please use images smaller than %dMB.' %
                      (settings.MAX_ICON_UPLOAD_SIZE / 1024 / 1024 - 1)))
        return icon

    def save(self):
        c = super(CollectionForm, self).save(commit=False)
        c.author = self.initial['author']
        c.application_id = self.initial['application_id']
        icon = self.cleaned_data.get('icon')

        if icon:
            c.icontype = 'image/png'

        c.save()
        if icon:
            dirname = os.path.join(settings.COLLECTIONS_ICON_PATH,
                                   str(c.id / 1000), )

            destination = os.path.join(dirname, '%d.png' % c.id)
            tmp_destination = os.path.join(dirname,
                                           '%d.png__unconverted' % c.id)

            if not os.path.exists(dirname):
                os.mkdir(dirname)

            fh = open(tmp_destination, 'w')
            for chunk in icon.chunks():
                fh.write(chunk)

            fh.close()
            # XXX
            # tasks.resize_icon.delay(tmp_destination, destination)

        for addon in self.cleaned_data['addon']:
            ca = CollectionAddon(collection=c, addon=addon)
            comment = self.cleaned_data['addon_comment'].get(addon.id)
            if comment:
                ca.comments = comment

            ca.save()
        c.save()  # Update counts, etc.

        return c

    class Meta:
        model = Collection
        fields = ('name', 'slug', 'description', 'listed')
