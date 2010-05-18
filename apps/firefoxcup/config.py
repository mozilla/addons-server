# coding=utf8
from tower import ugettext as _

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

def flag(name):
    return 'img/firefoxcup/flags/%s.png' % name

teams = {
    'algeria': {
        'name': _('Algeria')}, 
    'argentina': {
        'name': _('Argentina')},
    'australia': {
        'name': _('Australia')},
    'brazil': {
        'name': _('Brazil')},
    'cameroon': {
        'name': _('Cameroon')},
    'chile': {
        'name': _('Chile')},
    'cote': {
        'name': _("Cote d'Ivoire")},
    'denmark': {
        'name': _('Denmark')},
    'england': {
        'name': _('England')},
    'france': {
        'name': _('France')},
    'germany': {
        'name': _('Germany')},
    'ghana': {
        'name': _('Ghana')},
    'greece': {
        'name': _('Greece')},
    'honduras': {
        'name': _('Honduras')},
    'italy': {
        'name': _('Italy')},
    'japan': {
        'name': _('Japan')},
    'mexico': {
        'name': _('Mexico')},
    'netherlands': {
        'name': _('Netherlands')},
    'korea-dpr': {
        'name': _('North Korea')},
    'new-zealand': {
        'name': _('New Zealand')},
    'nigeria': {
        'name': _('Nigeria')},
    'paraguay': {
        'name': _('Paraguay')},
    'portugal': {
        'name': _('Portugal')},
    'serbia': {
        'name': _('Serbia')},
    'slovakia': {
        'name': _('Slovakia')},
    'slovenia': {
        'name': _('Slovenia')},
    'south-africa': {
        'name': _('South Africa')},
    'korea-republic': {
        'name': _('South Korea')},
    'spain': {
        'name': _('Spain')},
    'switzerland': {
        'name': _('Switzerland')},
    'usa': {
        'name': _('United States')},
    'uruguay': {
        'name': _('Uruguay')}
}    
for name in teams:
    teams[name]['flag'] = 'img/firefoxcup/flags/%s.png' % name

twitter_languages = (
    'ar','da','de','en','es','fa','fi','fr','hu',
    'is','it','ja','nl','no','pl','pt','ru','sv','th',
)

