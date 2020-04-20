from django.db import models

from olympia.addons.models import Addon
from olympia.amo.models import ModelBase


class GitExtraction(ModelBase):
    """
    This is an add-on related model that stores information related to the git
    extraction (for code-manager).
    """
    addon = models.OneToOneField(
        Addon, on_delete=models.CASCADE, primary_key=True
    )
    in_progress = models.BooleanField(default=False)
