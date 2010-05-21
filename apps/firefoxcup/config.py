# coding=utf8
from tower import ugettext as _
from settings import MEDIA_URL

tags = {
    'all': [
        '#worldcup', 
        '#football', 
        '#soccer', 
        '#south africa2010', 
        '#wcup2010'],
    'af': '#Wêreldbeker',
    'ar': ['كأس العالم','مونديال','المونديال','كأس العالم لكرة القدم' ],
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
        'persona': 813,
    }, 
    {
        'id': 'argentina',
        'name': _('Argentina'),
        'persona': 813,
    },
    {
        'id': 'australia',
        'name': _('Australia'),
        'persona': 813,
    },
    {
        'id': 'brazil',
        'name': _('Brazil'),
        'persona': 813,
    },
    {
        'id': 'cameroon',
        'name': _('Cameroon'),
        'persona': 813,
    },
    {
        'id': 'chile',
        'name': _('Chile'),
        'persona': 813,
    },
    {
        'id': 'cote',
        'name': _("Cote d'Ivoire"),
        'persona': 813,
    },
    {
        'id': 'denmark',
        'name': _('Denmark'),
        'persona': 813,
    },
    {
        'id': 'england',
        'name': _('England'),
        'persona': 813,
    },
    {
        'id': 'france',
        'name': _('France'),
        'persona': 813,
    },
    {
        'id': 'germany',
        'name': _('Germany'),
        'persona': 813,
    },
    {
        'id': 'ghana',
        'name': _('Ghana'),
        'persona': 813,
    },
    {
        'id': 'greece',
        'name': _('Greece'),
        'persona': 813,
    },
    {
        'id': 'honduras',
        'name': _('Honduras'),
        'persona': 813,
    },
    {
        'id': 'italy',
        'name': _('Italy'),
        'persona': 813,
    },
    {
        'id': 'japan',
        'name': _('Japan'),
        'persona': 813,
    },
    {
        'id': 'mexico',
        'name': _('Mexico'),
        'persona': 813,
    },
    {
        'id': 'netherlands',
        'name': _('Netherlands'),
        'persona': 813,
    },
    {
        'id': 'korea-dpr',
        'name': _('North Korea'),
        'persona': 813,
    },
    {
        'id': 'new-zealand',
        'name': _('New Zealand'),
        'persona': 813,
    },
    {
        'id': 'nigeria',
        'name': _('Nigeria'),
        'persona': 813,
    },
    {
        'id': 'paraguay',
        'name': _('Paraguay'),
        'persona': 813,
    },
    {
        'id': 'portugal',
        'name': _('Portugal'),
        'persona': 813,
    },
    {
        'id': 'serbia',
        'name': _('Serbia'),
        'persona': 813,
    },
    {
        'id': 'slovakia',
        'name': _('Slovakia'),
        'persona': 813,
    },
    {
        'id': 'slovenia',
        'name': _('Slovenia'),
        'persona': 813,
    },
    {
        'id': 'south-africa',
        'name': _('South Africa'),
        'persona': 813,
    },
    {
        'id': 'korea-republic',
        'name': _('South Korea'),
        'persona': 813,
    },
    {
        'id': 'spain',
        'name': _('Spain'),
        'persona': 813,
    },
    {
        'id': 'switzerland',
        'name': _('Switzerland'),
        'persona': 813,
    },
    {
        'id': 'usa',
        'name': _('United States'),
        'persona': 813,
    },
    {
        'id': 'uruguay',
        'name': _('Uruguay'),
        'persona': 813,
    }
]
for team in teams:
    team['flag'] = '%simg/firefoxcup/flags/%s.png' % (MEDIA_URL, team['id'])

twitter_languages = (
    'ar','da','de','en','es','fa','fi','fr','hu',
    'is','it','ja','nl','no','pl','pt','ru','sv','th',
)

