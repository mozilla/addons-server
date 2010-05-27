from django.db import models
from django.db.models import Avg

from amo.models import ModelBase, ManagerBase

class StatsManager(ManagerBase):

    def avg_fans(self):
        return self.values('persona_id').annotate(average=Avg('popularity'))


class Stats(ModelBase):
    """
    Keeps record of daily ADU counts for Firefox Cup personas.
    Used to calculate 'Average Fans' over time of Firefox Cup campaign
    """
    persona_id = models.PositiveIntegerField(db_index=True)
    popularity = models.PositiveIntegerField()

    objects = StatsManager()

    class Meta(ModelBase.Meta):
        db_table = 'stats_firefoxcup'
