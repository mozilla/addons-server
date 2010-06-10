from django.core.cache import cache

import cronjobs

from addons.models import Persona
from .models import Stats
from . import tags, teams as teams_config
from . import twitter


@cronjobs.register
def firefoxcup_stats():
    ids = [t['persona_id'] for t in teams_config]
    for p in Persona.objects.filter(persona_id__in=ids):
        Stats.objects.create(persona_id=p.persona_id, popularity=p.popularity)


@cronjobs.register
def firefoxcup_might_be_a_social_media_expert():
    # A hacky lock for this job that expires after 5 minutes.
    lock = 'fxcup-twitter-lock'
    if cache.add(lock, 1, 60 * 5):
        for lang in tags:
            twitter.cache_tweets(lang)
    cache.delete(lock)
