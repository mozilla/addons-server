import os

from django import forms
from django.conf import settings

import commonware.log
from tower import ugettext as _

import amo
from translations.widgets import TranslationTextInput, TranslationTextarea
from users.models import UserProfile
from .models import Collection, CollectionUser
from . import tasks

privacy_choices = (
        (False, _('Only I can view this collection.')),
        (True, _('Anybody can view this collection.')))

apps = ((a.id, a.pretty) for a in amo.APP_USAGE)
collection_types = ((k, v) for k, v in amo.COLLECTION_CHOICES.iteritems()
        if k not in (amo.COLLECTION_ANONYMOUS, amo.COLLECTION_RECOMMENDED))


log = commonware.log.getLogger('z.collections')


class AdminForm(forms.Form):
    application = forms.TypedChoiceField(choices=apps, required=False,
                                         coerce=int)
    type = forms.TypedChoiceField(choices=collection_types, required=False,
                                  coerce=int)

    def save(self, collection):
        collection.type = self.cleaned_data['type']
        collection.application_id = self.cleaned_data['application']
        collection.save()


class AddonsForm(forms.Form):
    """This form is related to adding addons to a collection."""

    addon = forms.CharField(widget=forms.MultipleHiddenInput, required=False)
    addon_comment = forms.CharField(widget=forms.MultipleHiddenInput,
                                     required=False)

    def clean_addon(self):
        return self.data.getlist('addon')

    def clean_addon_comment(self):
        addon_ids = self.data.getlist('addon')
        return dict(zip(map(int, addon_ids),
                        self.data.getlist('addon_comment')))

    def save(self, collection):
        collection.set_addons(self.cleaned_data['addon'],
                              self.cleaned_data['addon_comment'])


class ContributorsForm(forms.Form):
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
            log.info('%s was added to Collection %s' % (user.nickname,
                                                        collection.id))

        new_owner = self.cleaned_data['new_owner']

        if new_owner:
            old_owner = collection.author
            collection.author = new_owner

            cu, created = CollectionUser.objects.get_or_create(
                    collection=collection, user=old_owner)
            if created:
                cu.save()

            # Check for duplicate slugs.
            slug = collection.slug
            while new_owner.collections.filter(slug=slug).count():
                slug = slug + '-'
            collection.slug = slug
            collection.save()
            # New owner is no longer a contributor.
            collection.collectionuser_set.filter(user=new_owner).delete()

            log.info('%s now owns Collection %s' % (new_owner.nickname,
                                                    collection.id))


class CollectionForm(forms.ModelForm):

    name = forms.CharField(
            label=_('Give your collection a name.'),
            widget=TranslationTextInput,
            )
    slug = forms.CharField(label=_('URL:'))
    description = forms.CharField(
            label=_('Describe your collections.'),
            widget=TranslationTextarea,
            required=False)
    listed = forms.ChoiceField(
            label=_('Who can view your collection?'),
            widget=forms.RadioSelect,
            choices=privacy_choices,
            initial=True,
            )

    icon = forms.FileField(label=_('Give your collection an icon.'),
                           required=False)

    def clean_description(self):
        description = self.cleaned_data['description']
        if description.strip() == '':
            description = None

        return description

    def clean_slug(self):
        author = self.initial['author']
        slug = self.cleaned_data['slug']
        if self.instance and self.instance.slug == slug:
            return slug

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
            tasks.resize_icon.delay(tmp_destination, destination)

        return c

    class Meta:
        model = Collection
        fields = ('name', 'slug', 'description', 'listed')
