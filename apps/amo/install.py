import json
from jinja2 import Markup

import jingo
from django.http import HttpResponsePermanentRedirect, HttpResponseNotFound
from amo.utils import urlparams


REGEX = dict(
    mozilla='/^https?:\/\/([^\/]+\.)?mozilla\.(com|org)(\/.*)?$/',
    momo='/^https?:\/\/([^\/]+\.)?mozillamessaging\.com(\/.*)?$/',
    localhost='/^https?:\/\/([^\/]+\.)?localhost(\/.*)?$/',
    personas='/^https?:\/\/([^\/]+\.)?getpersonas\.com(\/.*)?$/',
    labs='/^https?:\/\/([^\/]+\.)?mozillalabs\.com(\/.*)?$/',
    stumbleupon='/^https?:\/\/([^\/]+\.)?stumbleupon\.com(\/.*)?$/',
    getfirebug='/^https?:\/\/([^\/]+\.)?getfirebug\.com(\/.*)?$/',
    ebay='/^https?:\/\/([^\/]+\.)?ebay\.(com|co\.uk|de|fr)(\/.*)?$/',
    twitter='/^https?:\/\/([^\/]+\.)?twitter\.com(\/.*)?$/'
)


def referrer(name):
    return 'document.referrer.match(%s)' % (REGEX[n],)

default_referrers = [referrer(n)
                     for n in ['mozilla', 'momo', 'localhost']]

addons = {
    # Firefox Updated Page add-ons
    'glubble': {
        'name': 'Glubble',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/5881',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/5881'
        },
    'googletoolbar': {
        'name': 'Google Toolbar',
        'link': 'http://tools.google.com/tools/firefox/toolbar/FT3/intl/en/install.html'
        },
    # Stumbleupon also used in Firefox 3 Get Personal
    138: {
        'name': 'StumbleUpon',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/138',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/138',
        'referrers': default_referrers + [referrer('stumbleupon')]
        },
    # Foxytunes also used in Firefox 3 Get Personal
    219: {
        'name': 'Foxytunes',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/219',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/219'
        },
    # Forecastfox also used in Firefox 3 Get Personal
    398: {
        'name': 'Forecastfox',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/398',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/398'
        },
    424: {
        'name': 'Wizz RSS News Reader',
        'link': 'https://addons.mozilla.org/en-US/firefox/addons/policy/0/424/19068',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/424'
        },
    1407: {
        'name': 'Clipmarks',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/1407'
        },
    # getfirebug.com installs
    1843: {
        'name': 'Firebug',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/1843',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/1843',
        'referrers': default_referrers + [referrer('getfirebug')]
        },
    # Foxmarks also used in Firefox 3 Get Personal
    2410: {
        'name': 'Foxmarks',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/2410',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/2410'
        },
    3348: {
        'name': 'Pronto Shopping Messenger',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/3348'
        },
    3945: {
        'name': 'Fotofox',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/3945'
        },
    # Firefox 3 Get Personal page
    # Forecastfox (see above)
    5202: {
        'name': 'eBay Companion',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/5202/platform:5/',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/5202',
        'referrers': default_referrers + [referrer('ebay')]
        },
    # Stumbleupon (see above)
    # Foxmarks (see above)
    # Foxytunes (see above)

    # Labs
    'personas': {
        'name': 'Personas for Firefox',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/10900',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/10900/1236031798',
        'referrers': default_referrers + [referrer('personas'), referrer('labs')]
        },
    'weave': {
        'name': 'Weave',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/10868',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/10868/1236131155',
        'referrers': default_referrers + [referrer('labs')]
        },
    'jetpack': {
        'name': 'Jetpack',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/12025',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/12025',
        'referrers': default_referrers + [referrer('labs')]
        },
    'prism': {
        'name': 'Prism for Firefox',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/6665',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/6665',
        'referrers': default_referrers + [referrer('labs')]
        },
    'ubiquity': {
        'name': 'Ubiquity',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/9527',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/9527',
        'referrers': default_referrers + [referrer('labs')]
        },
    'testpilot': {
        'name': 'Test Pilot',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/13661',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/13661',
        'referrers': default_referrers + [referrer('labs')]
        },
    # Twitter Address Search Bar
    318202: {
        'name': 'Twitter Address Search Bar',
        'xpi': 'https://addons.mozilla.org/en-US/firefox/downloads/latest/318202',
        'icon': 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/318202',
        'referrers': default_referrers + [referrer('twitter')]
        }
}

def install(request):
    addon_id = request.GET.get('addon_id', None)
    if addon_id:
        try:
            addon_id = int(addon_id)
        except ValueError:
            addon_id = Markup.escape(addon_id)
    addon_key = request.GET.get('addon_key', None)
    addon_name = request.GET.get('addon_name', None)
    if addon_id in addons:
        addon = addons[addon_id]
    elif addon_key in addons:
        addon = addons[addon_key]
    elif addon_name and addon_id:
        xpi = 'https://addons.mozilla.org/en-US/firefox/downloads/latest/%s' % addon_id
        icon = 'https://addons.mozilla.org/en-US/firefox/images/addon_icon/%s' % addon_id
        addon = {
            'name': addon_name,
            'xpi': xpi,
            'icon': icon
            }
    else:
        return HttpResponseNotFound()
    addon_link = addon.get('link', None)
    if addon_link:
        return HttpResponsePermanentRedirect(addon_link)
    if not 'xpi' in addon:
        return HttpResponseNotFound()
    src = request.GET.get('src', 'installservice')
    addon['xpi'] = urlparams(addon['xpi'], src=src)
    addon_params = {'URL': addon['xpi']}
    if 'icon' in addon:
        addon_params['IconURL'] = addon['icon']
    if 'hash' in addon:
        addon_params['Hash'] = addon['hash']
    referrers = ' || '.join(addon.get('referrers', default_referrers))
    return jingo.render(request, 'services/install.html',
                        {'referrers': referrers,
                         'params': json.dumps({'name': addon_params}),
                         'addon': addon})
