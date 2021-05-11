from django.db import models

from olympia.addons.models import Addon
from olympia.amo.models import ModelBase


class GitExtractionEntry(ModelBase):
    """
    This is a model that represents an entry in a "queue" of add-ons scheduled
    for git extraction. When an add-on is in this queue, its versions should be
    extracted to a git repository.
    """

    addon = models.ForeignKey(Addon, on_delete=models.CASCADE)
    in_progress = models.BooleanField(default=None, null=True)

    class Meta(ModelBase.Meta):
        unique_together = ('addon', 'in_progress')
        verbose_name_plural = 'Git extraction entries'

    def __str__(self):
        return 'Entry for "{}" (in_progress={})'.format(
            str(self.addon), self.in_progress
        )
