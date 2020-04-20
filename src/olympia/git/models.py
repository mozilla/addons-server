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


class GitExtractionQueue(ModelBase):
    """
    This is a model that represents a queue of add-ons for git extraction. When
    an add-on is in this queue, its versions should be extracted to a git repo.
    """

    addon = models.ForeignKey(Addon, on_delete=models.CASCADE, null=True)
