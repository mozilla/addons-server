import amo
from addons.models import Addon


# We use super(Addon, self) on purpose to override expectations in Addon that
# are not true for Webapp. Webapp is just inheriting so it can share the db
# table.
class Webapp(Addon):
    # TODO: find a place to store the app version number.

    class Meta:
        proxy = True

    def save(self, **kw):
        # Make sure we have the right type.
        self.type = amo.ADDON_WEBAPP
        self.clean_slug(slug_field='app_slug')
        creating = not self.id
        super(Addon, self).save(**kw)
        # Set the slug once we have an id to keep things in order.
        if creating:
            self.update(slug='app-%s' % self.id)
