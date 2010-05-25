from django.db import models

import amo.models


class FirefoxcupStat(amo.models.ModelBase):
    """
    Keeps record of daily ADU counts for Firefox Cup personas.
    Used to calculate 'Average Fans' over time of Firefox Cup campaign
    """
    persona = models.ForeignKey('addons.Persona')
    adu = models.IntegerField()

    class Meta:
        db_table = 'firefoxcup_stats'
