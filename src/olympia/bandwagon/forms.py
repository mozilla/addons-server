import os

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.utils.translation import ugettext, ugettext_lazy as _

from django_statsd.clients import statsd

import olympia.core.logger

from olympia import amo
from olympia.amo.utils import (
    clean_nl, has_links, ImageCheck, slug_validator, slugify)
from olympia.translations.widgets import (
    TranslationTextarea, TranslationTextInput)
from olympia.users.models import DeniedName

from . import tasks
from .models import Collection


privacy_choices = (
    (False, _(u'Only I can view this collection.')),
    (True, _(u'Anybody can view this collection.')))

apps = (('', None),) + tuple((a.id, a.pretty) for a in amo.APP_USAGE)
collection_types = (
    (k, v) for k, v in amo.COLLECTION_CHOICES.iteritems()
    if k not in (amo.COLLECTION_ANONYMOUS, amo.COLLECTION_RECOMMENDED))


log = olympia.core.logger.getLogger('z.collections')


class AddonsForm(forms.Form):
    """This form is related to adding addons to a collection."""

    addon = forms.CharField(widget=forms.MultipleHiddenInput, required=False)
    addon_comment = forms.CharField(widget=forms.MultipleHiddenInput,
                                    required=False)

    def clean_addon(self):
        addons = []
        for a in self.data.getlist('addon'):
            try:
                addons.append(int(a))
            except ValueError:
                pass

        return addons

    def clean_addon_comment(self):
        fields = 'addon', 'addon_comment'
        rv = {}
        for addon, comment in zip(*map(self.data.getlist, fields)):
            try:
                rv[int(addon)] = comment
            except ValueError:
                pass
        return rv

    def save(self, collection):
        collection.set_addons(self.cleaned_data['addon'],
                              self.cleaned_data['addon_comment'])


class CollectionForm(forms.ModelForm):

    name = forms.CharField(
        label=_(u'Give your collection a name.'),
        widget=TranslationTextInput)
    slug = forms.CharField(label=_(u'URL:'))
    description = forms.CharField(
        label=_(u'Describe your collection (no links allowed).'),
        widget=TranslationTextarea(attrs={'rows': 3}),
        max_length=200,
        required=False)
    listed = forms.ChoiceField(
        label=_(u'Privacy:'),
        widget=forms.RadioSelect,
        choices=privacy_choices,
        initial=True)

    # This is just a honeypot field for bots to get caught
    # L10n: bots is short for robots
    your_name = forms.CharField(
        label=_(
            u"Please don't fill out this field, it's used to catch bots"),
        required=False)

    def __init__(self, *args, **kw):
        super(CollectionForm, self).__init__(*args, **kw)
        # You can't edit the slugs for the special types.
        if (self.instance and
                self.instance.type in amo.COLLECTION_SPECIAL_SLUGS):
            del self.fields['slug']

    def clean(self):
        # Check the honeypot here instead of 'clean_your_name' so the
        # error message appears at the top of the form in the __all__ section
        if self.cleaned_data['your_name']:
            statsd.incr('collections.honeypotted')
            log.info('Bot trapped in honeypot at collections.create')
            raise forms.ValidationError(
                "You've been flagged as spam, sorry about that.")
        return super(CollectionForm, self).clean()

    def clean_name(self):
        name = self.cleaned_data['name']
        if DeniedName.blocked(name):
            raise forms.ValidationError(ugettext('This name cannot be used.'))
        return name

    def clean_description(self):
        description = self.cleaned_data['description']
        normalized = clean_nl(description)
        if has_links(normalized):
            # There's some links, we don't want them.
            raise forms.ValidationError(ugettext('No links are allowed.'))
        return description

    def clean_slug(self):
        slug = slugify(self.cleaned_data['slug'])
        slug_validator(slug)
        if self.instance and self.instance.slug == slug:
            return slug

        author = self.initial['author']
        if author.collections.filter(slug=slug).count():
            raise forms.ValidationError(
                ugettext('This url is already in use by another collection'))

        return slug

    def save(self, default_locale=None):
        collection = super(CollectionForm, self).save(commit=False)
        collection.author = self.initial['author']
        collection.application = self.initial['application']

        if default_locale:
            collection.default_locale = default_locale

        collection.save()

        return collection

    class Meta:
        model = Collection
        fields = ('name', 'slug', 'description', 'listed')
