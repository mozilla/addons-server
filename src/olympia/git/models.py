from django.db import models

from olympia.addons.models import Addon
from olympia.amo.models import ModelBase


class AddonGitExtraction(ModelBase):
    """
    This is an add-on related model that stores information related to the git
    extraction (for code-manager).
    """

    addon = models.OneToOneField(
        Addon, on_delete=models.CASCADE, primary_key=True
    )
    in_progress = models.BooleanField(default=False)


class GitExtractionEntry(ModelBase):
    """
    This is a model that represents an entry in a "queue" of add-ons scheduled
    for git extraction. When an add-on is in this queue, its versions should be
    extracted to a git repository.
    """

    addon = models.ForeignKey(Addon, on_delete=models.CASCADE, null=True)
