from django.db import models

import amo
from addons.models import Addon


class Version(amo.ModelBase):

    addon = models.ForeignKey(Addon)

    class Meta(amo.ModelBase.Meta):
        db_table = 'versions'
