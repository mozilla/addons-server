import os

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.utils.translation import ugettext, ugettext_lazy as _

from django_statsd.clients import statsd

import olympia.core.logger
from olympia import amo
from olympia.amo.utils import clean_nl, has_links, slug_validator, slugify
from olympia.lib import happyforms
from olympia.translations.widgets import (
    TranslationTextInput, TranslationTextarea)
from olympia.users.models import DeniedName, UserProfile

from .models import Collection, CollectionUser
from . import tasks

privacy_choices = (
    (False, _(u'Only I can view this collection.')),
    (True, _(u'Anybody can view this collection.')))

apps = (('', None),) + tuple((a.id, a.pretty) for a in amo.APP_USAGE)
collection_types = (
    (k, v) for k, v in amo.COLLECTION_CHOICES.iteritems()
    if k not in (amo.COLLECTION_ANONYMOUS, amo.COLLECTION_RECOMMENDED))


log = olympia.core.logger.getLogger('z.collections')


class AdminForm(happyforms.Form):
    application = forms.TypedChoiceField(choices=apps, required=False,
                                         empty_value=None, coerce=int)
    type = forms.TypedChoiceField(choices=collection_types, required=False,
                                  coerce=int)

    def save(self, collection):
        collection.type = self.cleaned_data['type']
        collection.application = self.cleaned_data['application']
        collection.save()


class AddonsForm(happyforms.Form):
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


class ContributorsForm(happyforms.Form):
    """This form is related to adding contributors to a collection."""

    contributor = forms.CharField(widget=forms.MultipleHiddenInput,
                                  required=False)

    new_owner = forms.CharField(widget=forms.HiddenInput, required=False)

    def clean_new_owner(self):
        new_owner = self.cleaned_data['new_owner']
        if new_owner:
            return UserProfile.objects.get(email=new_owner)

    def clean_contributor(self):
        contributor_emails = self.data.getlist('contributor')
        return UserProfile.objects.filter(email__in=contributor_emails)

    def save(self, collection):
        collection.collectionuser_set.all().delete()
        for user in self.cleaned_data['contributor']:
            CollectionUser(collection=collection, user=user).save()
            log.info('%s was added to Collection %s' % (user.username,
                                                        collection.id))

        new_owner = self.cleaned_data['new_owner']

        if new_owner:
            old_owner = collection.author
            collection.author = new_owner

            cu, created = CollectionUser.objects.get_or_create(
                collection=collection, user=old_owner)
            if created:
                cu.save()

            collection.save()
            # New owner is no longer a contributor.
            collection.collectionuser_set.filter(user=new_owner).delete()

            log.info('%s now owns Collection %s' % (new_owner.username,
                                                    collection.id))


class CollectionForm(happyforms.ModelForm):

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

    icon = forms.FileField(label=_(u'Icon'),
                           required=False)

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

    def clean_icon(self):
        icon = self.cleaned_data['icon']
        if not icon:
            return
        if icon.content_type not in ('image/png', 'image/jpeg'):
            raise forms.ValidationError(
                ugettext('Icons must be either PNG or JPG.'))

        if icon.size > settings.MAX_ICON_UPLOAD_SIZE:
            size_in_mb = settings.MAX_ICON_UPLOAD_SIZE / 1024 / 1024 - 1
            raise forms.ValidationError(
                ugettext('Please use images smaller than %dMB.') % size_in_mb)
        return icon

    def save(self, default_locale=None):
        c = super(CollectionForm, self).save(commit=False)
        c.author = self.initial['author']
        c.application = self.initial['application']
        icon = self.cleaned_data.get('icon')

        if default_locale:
            c.default_locale = default_locale

        if icon:
            c.icontype = 'image/png'

        c.save()

        if icon:
            dirname = c.get_img_dir()

            destination = os.path.join(dirname, '%d.png' % c.id)
            tmp_destination = os.path.join(dirname,
                                           '%d.png__unconverted' % c.id)
            with storage.open(tmp_destination, 'w') as fh:
                for chunk in icon.chunks():
                    fh.write(chunk)
            tasks.resize_icon.delay(tmp_destination, destination,
                                    set_modified_on=[c])

        return c

    class Meta:
        model = Collection
        fields = ('name', 'slug', 'description', 'listed')
