import amo
from addons.models import Addon
from versions.models import Version


# We use super(Addon, self) on purpose to override expectations in Addon that
# are not true for Webapp. Webapp is just inheriting so it can share the db
# table.
class Webapp(Addon):

    class Meta:
        proxy = True

    def save(self, **kw):
        # Make sure we have the right type.
        self.type = amo.ADDON_WEBAPP
        self.clean_slug(slug_field='app_slug')
        creating = not self.id
        super(Addon, self).save(**kw)
        if creating:
            # Set current_version since a lot of things expect it.
            version = Version.objects.create(addon=self, version='0')
            # Set the slug once we have an id to keep things in order.
            self.update(slug='app-%s' % self.id, _current_version=version)


# These are the translated strings we want to pull in.
translated = 'name', 'summary', 'description'
Webapp._meta.translated_fields = [f for f in Webapp._meta.fields
                                  if f.name in translated]
