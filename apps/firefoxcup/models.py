from django.db import models

from amo.models import ModelBase


class Stats(ModelBase):
    """
    Keeps record of daily ADU counts for Firefox Cup personas.
    Used to calculate 'Average Fans' over time of Firefox Cup campaign
    """
    persona_id = models.PositiveIntegerField(db_index=True)
    popularity = models.PositiveIntegerField()

    class Meta(ModelBase.Meta):
        db_table = 'stats_firefoxcup'
