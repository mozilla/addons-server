from django.db import models

from addons.models import Category
from mkt.webapps.models import Webapp


class FeaturedApp(models.Model):
    app = models.ForeignKey(Webapp, null=False)
    category = models.ForeignKey(Category, null=True)
    is_sponsor = models.BooleanField(default=False)

    class Meta:
        db_table = 'zadmin_featuredapp'
