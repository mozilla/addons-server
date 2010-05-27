from datetime import datetime

import commonware.log

import cronjobs

from addons.models import Persona
from .models import Stats
from . import teams as teams_config

log = commonware.log.getLogger('z.cron')


@cronjobs.register
def firefoxcup_stats(teams=teams_config):
    try:
        latest = Stats.objects.latest()
        delta = datetime.today() - latest.created
        if delta.days < 1:
            return
    except Stats.DoesNotExist:
        pass

    ids = [t['persona_id'] for t in teams]
    for p in Persona.objects.filter(persona_id__in=ids):
        Stats.objects.create(persona_id=p.persona_id, popularity=p.popularity)
