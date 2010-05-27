# coding=utf8
from django.conf import settings
from tower import ugettext_lazy as _

email_enabled = False

tags = {
    'all': [
        '#worldcup',
        '#football',
        '#soccer',
        '#south africa2010',
        '#wcup2010'],
    'af': '#Wêreldbeker',
    'ar': ['كأس العالم', 'مونديال', 'المونديال', 'كأس العالم لكرة القدم'],
    'da': ['#vm', 'Fodbold VM'],
    'de': '#wm',
    'es': '#mundial',
    'fr': ['#mondial', '#coupedumonde'],
    'it': '#IlMondiale',
    'ja': '#W杯',
    'ko': '#월드컵',
    'nl': ['#wk', '#wereldbeker', '#oranje'],
    'ru': 'ЧМ',
    'sr': 'Светско првенство',
    'sk': 'Svetový pohár',
    'sl': 'Svetovni pokal',
}

teams = [
    {
        'id': 'algeria',
        'name': _('Algeria'),
        'persona_id': 216601,
    },
    {
        'id': 'argentina',
        'name': _('Argentina'),
        'persona_id': 216091,
    },
    {
        'id': 'australia',
        'name': _('Australia'),
        'persona_id': 216602,
    },
    {
        'id': 'brazil',
        'name': _('Brazil'),
        'persona_id': 216603,
    },
    {
        'id': 'cameroon',
        'name': _('Cameroon'),
        'persona_id': 216605,
    },
    {
        'id': 'chile',
        'name': _('Chile'),
        'persona_id': 216606,
    },
    {
        'id': 'cote',
        'name': _("Cote d'Ivoire"),
        'persona_id': 216626,
    },
    {
        'id': 'denmark',
        'name': _('Denmark'),
        'persona_id': 216608,
    },
    {
        'id': 'england',
        'name': _('England'),
        'persona_id': 215499,
    },
    {
        'id': 'france',
        'name': _('France'),
        'persona_id': 215503,
    },
    {
        'id': 'germany',
        'name': _('Germany'),
        'persona_id': 215502,
    },
    {
        'id': 'ghana',
        'name': _('Ghana'),
        'persona_id': 216610,
    },
    {
        'id': 'greece',
        'name': _('Greece'),
        'persona_id': 216618,
    },
    {
        'id': 'honduras',
        'name': _('Honduras'),
        'persona_id': 216624,
    },
    {
        'id': 'italy',
        'name': _('Italy'),
        'persona_id': 215504,
    },
    {
        'id': 'japan',
        'name': _('Japan'),
        'persona_id': 215506,
    },
    {
        'id': 'mexico',
        'name': _('Mexico'),
        'persona_id': 216597,
    },
    {
        'id': 'netherlands',
        'name': _('Netherlands'),
        'persona_id': 216093,
    },
    {
        'id': 'korea-dpr',
        'name': _('North Korea'),
        'persona_id': 216630,
    },
    {
        'id': 'new-zealand',
        'name': _('New Zealand'),
        'persona_id': 216627,
    },
    {
        'id': 'nigeria',
        'name': _('Nigeria'),
        'persona_id': 216629,
    },
    {
        'id': 'paraguay',
        'name': _('Paraguay'),
        'persona_id': 216631,
    },
    {
        'id': 'portugal',
        'name': _('Portugal'),
        'persona_id': 216635,
    },
    {
        'id': 'serbia',
        'name': _('Serbia'),
        'persona_id': 216641,
    },
    {
        'id': 'slovakia',
        'name': _('Slovakia'),
        'persona_id': 216646,
    },
    {
        'id': 'slovenia',
        'name': _('Slovenia'),
        'persona_id': 216648,
    },
    {
        'id': 'south-africa',
        'name': _('South Africa'),
        'persona_id': 216652,
    },
    {
        'id': 'korea-republic',
        'name': _('South Korea'),
        'persona_id': 216668,
    },
    {
        'id': 'spain',
        'name': _('Spain'),
        'persona_id': 215498,
    },
    {
        'id': 'switzerland',
        'name': _('Switzerland'),
        'persona_id': 216670,
    },
    {
        'id': 'usa',
        'name': _('United States'),
        'persona_id': 215507,
    },
    {
        'id': 'uruguay',
        'name': _('Uruguay'),
        'persona_id': 216672,
    }]

for team in teams:
    team['flag'] = '%simg/firefoxcup/flags/%s.png' % (settings.MEDIA_URL,
                                                      team['id'])
    team['persona'] = None

twitter_languages = """
    ar da de en es fa fi fr hu is it ja nl no pl pt ru sv th""".split()
