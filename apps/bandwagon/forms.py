import os

from django import forms
from django.conf import settings

import commonware.log
from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from amo.utils import slugify, slug_validator
from happyforms import Form, ModelForm
from translations.widgets import TranslationTextInput, TranslationTextarea
from users.models import UserProfile
from .models import Collection, CollectionUser
from . import tasks

privacy_choices = (
        (False, _lazy('Only I can view this collection.')),
        (True, _lazy('Anybody can view this collection.')))

apps = (('', None),) + tuple((a.id, a.pretty) for a in amo.APP_USAGE)
collection_types = ((k, v) for k, v in amo.COLLECTION_CHOICES.iteritems()
        if k not in (amo.COLLECTION_ANONYMOUS, amo.COLLECTION_RECOMMENDED))


log = commonware.log.getLogger('z.collections')


class AdminForm(Form):
    application = forms.TypedChoiceField(choices=apps, required=False,
                                         empty_value=None, coerce=int)
    type = forms.TypedChoiceField(choices=collection_types, required=False,
                                  coerce=int)

    def save(self, collection):
        collection.type = self.cleaned_data['type']
        collection.application_id = self.cleaned_data['application']
        collection.save()


class AddonsForm(Form):
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


class ContributorsForm(Form):
    """This form is related to adding contributors to a collection."""

    contributor = forms.CharField(widget=forms.MultipleHiddenInput,
                                 required=False)

    new_owner = forms.IntegerField(widget=forms.HiddenInput, required=False)

    def clean_new_owner(self):
        new_owner = self.cleaned_data['new_owner']
        if new_owner:
            return UserProfile.objects.get(pk=new_owner)

    def clean_contributor(self):
        contributor_ids = self.data.getlist('contributor')
        return UserProfile.objects.filter(pk__in=contributor_ids)

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


class CollectionForm(ModelForm):

    name = forms.CharField(
            label=_lazy('Give your collection a name.'),
            widget=TranslationTextInput,
            )
    slug = forms.CharField(label=_lazy('URL:'))
    description = forms.CharField(
            label=_lazy('Describe your collection.'),
            widget=TranslationTextarea(attrs={'rows': 3}),
            max_length=200,
            required=False)
    listed = forms.ChoiceField(
            label=_lazy('Privacy:'),
            widget=forms.RadioSelect,
            choices=privacy_choices,
            initial=True,
            )

    icon = forms.FileField(label=_lazy('Icon'),
                           required=False)

    def __init__(self, *args, **kw):
        super(CollectionForm, self).__init__(*args, **kw)
        # You can't edit the slugs for the special types.
        if (self.instance and
            self.instance.type in amo.COLLECTION_SPECIAL_SLUGS):
            del self.fields['slug']

    def clean_description(self):
        description = self.cleaned_data['description']
        if description.strip() == '':
            description = None

        return description

    def clean_slug(self):
        slug = slugify(self.cleaned_data['slug'])
        slug_validator(slug)
        if self.instance and self.instance.slug == slug:
            return slug

        author = self.initial['author']
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

    def save(self, default_locale=None):
        c = super(CollectionForm, self).save(commit=False)
        c.author = self.initial['author']
        c.application_id = self.initial['application_id']
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

            if not os.path.exists(dirname):
                os.mkdir(dirname)

            fh = open(tmp_destination, 'w')
            for chunk in icon.chunks():
                fh.write(chunk)

            fh.close()
            tasks.resize_icon.delay(tmp_destination, destination)

        return c

    class Meta:
        model = Collection
        fields = ('name', 'slug', 'description', 'listed')
