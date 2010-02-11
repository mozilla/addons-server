from django.db import models

from amo import fields


class DecimalCharFieldModel(models.Model):
    strict = fields.DecimalCharField(max_digits=10, decimal_places=2)
    loose = fields.DecimalCharField(max_digits=10, decimal_places=2,
                                    nullify_invalid=True, null=True)
