import jingo
from addons.models import Persona
from twitter import search
from . import tags, email_enabled
from . import teams as teams_config

import logging

log = logging.getLogger('z.firefoxcup')

# Create your views here.
def index(request):

    tweets = search(tags['all'], lang=request.LANG)

    if len(tweets) < 15:
        extra = search(tags['all'], 'all')
        tweets.extend(extra)

    # we only want 15 tweets
    tweets = tweets[:15]

    teams = dict((t['persona_id'], t) for t in teams_config)
    for persona in Persona.objects.filter(persona_id__in=teams.keys()):
        teams[persona.persona_id]['persona'] = persona

    return jingo.render(request, 'firefoxcup/index.html', {
        'tweets': tweets,
        'teams': teams.values(),
        'email_enabled': email_enabled,
    })
