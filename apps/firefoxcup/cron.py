import cronjobs

from addons.models import Persona
from .models import Stats
from . import teams as teams_config


@cronjobs.register
def firefoxcup_stats():
    ids = [t['persona_id'] for t in teams_config]
    for p in Persona.objects.filter(persona_id__in=ids):
        Stats.objects.create(persona_id=p.persona_id, popularity=p.popularity)
