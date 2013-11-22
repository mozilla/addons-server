# -*- coding: utf-8 -*-
from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect

import basket
import commonware.log
import jingo
from session_csrf import anonymous_csrf
from tower import ugettext as _

from amo import messages
from mkt.developers.forms import DevNewsletterForm


log = commonware.log.getLogger('z.ecosystem')


@anonymous_csrf
def landing(request):
    """Developer Hub landing page."""
    videos = [
        {
            'name': 'airbnb',
            'path': 'FirefoxMarketplace-airbnb-BR-RC-SD1%20640'
        },
        {
            'name': 'evernote',
            'path': 'FirefoxMarketplace-Evernote_BR-RC-SD1%20640'
        },
        {
            'name': 'uken',
            'path': 'FirefoxMarketplace-uken-BR-RC-SD1%20640'
        },
        {
            'name': 'soundcloud',
            'path': 'FirefoxMarketplace-Soundcloud-BR-RC-SD1%20640'
        },
        {
            'name': 'box',
            'path': 'FirefoxMarketplace_box-BR-RC-SD1%20640'
        }
    ]

    form = DevNewsletterForm(request.LANG, request.POST or None)

    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data

        try:
            basket.subscribe(data['email'],
                             'app-dev',
                             format=data['email_format'],
                             source_url=settings.SITE_URL)
            messages.success(request, _('Thank you for subscribing!'))
            return redirect('ecosystem.landing')
        except basket.BasketException as e:
            log.error(
                'Basket exception in ecosystem newsletter: %s' % e)
            messages.error(
                request, _('We apologize, but an error occurred in our '
                           'system. Please try again later.'))

    return jingo.render(request, 'ecosystem/landing.html',
        {'videos': videos, 'newsletter_form': form})


def support(request):
    """Landing page for support."""
    return jingo.render(request, 'ecosystem/support.html',
        {'page': 'support', 'category': 'build'})


def partners(request):
    """Landing page for partners."""
    return jingo.render(request, 'ecosystem/partners.html',
        {'page': 'partners'})


def installation(request):
    """Landing page for installation."""
    return jingo.render(request, 'ecosystem/installation.html',
        {'page': 'installation', 'category': 'publish'})


def dev_phone(request):
    """Landing page for the developer phone."""
    return jingo.render(request, 'ecosystem/dev_phone.html',
        {'page': 'dev_phone'})


def design_ui(request):
    """Design - UI Guidelines page."""
    return jingo.render(request, 'ecosystem/design_ui.html',
        {'page': 'design_ui', 'category': 'design'})


def publish_deploy(request):
    """Publish - Deploying your app page."""
    return jingo.render(request, 'ecosystem/publish_deploy.html',
        {'page': 'publish_deploy', 'category': 'publish'})


def publish_payments(request):
    """Publish - Marketplace payments status."""
    return jingo.render(request, 'ecosystem/publish_payments.html',
        {'page': 'publish_payments', 'category': 'publish'})


def publish_badges(request):
    """Publish - Marketplace badges."""
    return jingo.render(request, 'ecosystem/publish_badges.html',
        {'page': 'badges', 'category': 'publish'})


def build_app_generator(request):
    """Build - App Generator page."""
    app_generators = [
        {
            'css_name': 'app-stub',
            'title': _('App Stub'),
            'download': 'https://github.com/mozilla/mortar-app-stub/archive/v0.1.0.zip',
            'preview': 'app-stub-screenshot.png',
            'description': _('App Stub is the simplest of the app templates: '
                             'It provides an unstyled HTML document and is '
                             'therefore the best choice for porting over '
                             'existing web content or for implementing an '
                             'existing design.'),
            'features': [
                _('well-structured and minimal HTML to get started quickly'),
                _('<a href="http://requirejs.org" rel="external" '
                  'target="_blank">RequireJS</a> for JavaScript management'),
                _('<a href="http://volojs.org" rel="external" '
                  'target="_blank">Volo.js</a> for adding JavaScript '
                  'packages, compiling assets, and deploying to Github')
            ]
        },
        {
            'css_name': 'list-detail-view',
            'title': _('List/Detail View'),
            'download': 'https://github.com/mozilla/mortar-list-detail/archive/v0.1.0.zip',
            'preview': 'list-view-stub-screenshot.png',
            'description': _('In addition to all the basic app template '
                             'features, the List/Detail View template '
                             'provides a simple list of content items and '
                             'a details page for each of them. The template '
                             'simplifies common app tasks, like automated '
                             'content updating across the app, intelligent '
                             'back button behavior, etc.'),
            'features': [
                _('includes all of <a href="https://github.com/mozilla/mortar-app-stub">'
                  'App Stub\'s</a> features'),
                _('a navigation stack for managing app structure'),
                _('a header element and automatic back button'),
                _('data propagation across the app, via '
                  '<a href="http://backbonejs.org">Backbone.js</a>')
            ]
        },
        {
            'css_name': 'game-stub',
            'title': _('Game Stub'),
            'download': 'https://github.com/mozilla/mortar-game-stub/archive/v0.1.0.zip',
            'preview': 'game-stub-screenshot.png',
            'description': _('Game Stub is a template for developing 2D '
                             'Games apps in HTML5, CSS and JavaScript. It '
                             'greatly reduces the time spent on the basics '
                             'of games development, such as creating a '
                             'canvas and an event loop.'),
            'features': [
                _('includes all of <a href="https://github.com/mozilla/mortar-app-stub">'
                  'App Stub\'s</a> features'),
                _('a canvas element and example code drawing a game entity '
                  'onto it'),
                _('an event loop using requestAnimationFrame'),
                _('a means to pause and unpause the game as the app loses '
                  'and regains focus')
            ]
        }
    ]

    d = {
        'page': 'build_app_generator',
        'category': 'build',
        'app_generators': app_generators
    }
    return jingo.render(request, 'ecosystem/build_app_generator.html', d)


def build_tools(request):
    """Build - Tools page."""
    return jingo.render(request, 'ecosystem/build_tools.html',
        {'page': 'build_tools', 'category': 'build'})


def build_dev_tools(request):
    """Build - Developer Tools page."""
    return jingo.render(request, 'ecosystem/build_dev_tools.html',
        {'page': 'build_dev_tools', 'category': 'build'})


def apps_documentation(request, page=None):
    """Page template for all reference apps."""

    if page not in ('chrono', 'face_value', 'podcasts', 'roller',
                    'webfighter', 'generalnotes', 'rtcamera'):
        raise Http404

    third_party_libs = {
        'node': {
            'link': 'http://nodejs.org/',
            'title': 'Node.js',
        },
        'zepto': {
            'link': 'http://zeptojs.com/',
            'title': 'zepto.js',
        },
        'backbone': {
            'link': 'http://backbonejs.org/',
            'title': 'backbone.js',
        },
        'redis': {
            'link': 'http://redis.io',
            'title': 'redis',
        },
        'volo': {
            'link': 'http://volojs.org/',
            'title': 'volo.js',
        },
        'jquery': {
            'link': 'http://jquery.com/',
            'title': 'jQuery',
        },
        'requirejs': {
            'link': 'http://requirejs.org/',
            'title': 'RequireJS',
        },
        'animated_gif': {
            'link': 'https://github.com/sole/Animated_GIF',
            'title': 'Animated GIF',
        },
        'async_storage': {
            'link': 'https://github.com/mozilla-b2g/gaia/blob/master/shared/js/async_storage.js',
            'title': 'Async Storage',
        },
        'glmatrix': {
            'link': 'http://glmatrix.net',
            'title': 'glMatrix',
        },
        'hammerjs': {
            'link': 'http://eightmedia.github.io/hammer.js',
            'title': 'hammer.js',
        }
    }

    web_api_libs = {
        'localstorage': {
            'link': '//developer.mozilla.org/docs/DOM/Storage#localStorage',
            'title': 'localStorage',
        },
        'appcache': {
            'link': '//developer.mozilla.org/docs/HTML/Using_the_application_cache',
            'title': 'appcache',
        },
        'open_web_apps': {
            'link': '//developer.mozilla.org/docs/Apps/Apps_JavaScript_API',
            'title': 'Open Web Apps',
        },
        'indexed_db': {
            'link': '//developer.mozilla.org/docs/IndexedDB',
            'title': 'IndexedDB',
        },
        'systemxhr': {
            'link': '//developer.mozilla.org/docs/DOM/XMLHttpRequest#Non-standard_properties',
            'title': 'systemXHR',
        },
        'canvas': {
            'link': '//developer.mozilla.org/docs/HTML/Canvas',
            'title': 'Canvas',
        },
        'fullscreen': {
            'link': '//developer.mozilla.org/docs/DOM/Using_fullscreen_mode',
            'title': 'Fullscreen'
        },
        'in_app_payments': {
            'link': '//developer.mozilla.org/docs/Web/Apps/Publishing/In-app_payments',
            'title': 'In-app Payments',
        },
        'blob': {
            'link': '//developer.mozilla.org/docs/Web/API/Blob',
            'title': 'Blob',
        },
        'url': {
            'link': '//developer.mozilla.org/docs/Web/API/window.URL',
            'title': 'URL',
        },
        'webgl': {
            'link': '//developer.mozilla.org/docs/Web/WebGL',
            'title': 'WebGL',
        },
        'webrtc': {
            'link': '//developer.mozilla.org/docs/WebRTC',
            'title': 'WebRTC',
        },
        'getusermedia': {
            'link': '//developer.mozilla.org/docs/Web/API/Navigator.getUserMedia',
            'title': 'getUserMedia',
        },
        'webworkers': {
            'link': '//developer.mozilla.org/docs/Web/API/Worker',
            'title': 'Web Workers',
        },
        'xmlhttprequest': {
            'link': '//developer.mozilla.org/docs/Web/API/XMLHttpRequest',
            'title': 'XMLHttpRequest',
        }
    }

    custom_elements_libs = {
        'gaia': {
            'link': 'https://wiki.mozilla.org/Gaia/Design/BuildingBlocks',
            'title': _('Gaia Building Blocks'),
        },
        'xtags': {
            'link': 'http://x-tags.org',
            'title': 'x-tags',
        }
    }

    ctx = {
        'page': page,
        'category': 'build',
        'third_party_libs': third_party_libs,
        'web_api_libs': web_api_libs,
        'custom_elements_libs': custom_elements_libs
    }

    return jingo.render(request, ('ecosystem/reference_apps/%s.html' % page),
           ctx)
