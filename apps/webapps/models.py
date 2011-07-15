import amo
from addons.models import Addon


# I don't know if we'll want to inherit and extend the Addon class so we'll
# start with a proxy for now.
class Webapp(Addon):

    # TODO: give apps a separate slug namespace from add-ons.
    # TODO: find a place to store the app version number.

    class Meta:
        proxy = True

    def save(self, **kw):
        # Make sure we have the right type.
        self.type = amo.ADDON_WEBAPP
        super(Webapp, self).save(**kw)
