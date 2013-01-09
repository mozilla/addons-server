from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect

import basket
import commonware.log
import jingo
from session_csrf import anonymous_csrf
from tower import ugettext as _

from amo import messages
from mkt.developers.forms import DevNewsletterForm
from mkt.ecosystem.tasks import refresh_mdn_cache
from mkt.site import messages

from .models import MdnCache
from .tasks import locales


log = commonware.log.getLogger('z.ecosystem')


def _refresh_mdn(request):
    if settings.MDN_LAZY_REFRESH and 'refresh' in request.GET:
        # If you can delay this, please teach me. I give up.
        refresh_mdn_cache()
        messages.success(request,
            'Pulling new content from MDN. Please check back in a few minutes.'
            ' Thanks for all your awesome work! Devs appreciate it!')


@anonymous_csrf
def landing(request):
    """Developer Hub landing page."""
    _refresh_mdn(request)

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

    form = DevNewsletterForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data

        try:
            basket.subscribe(data['email'],
                             'app-dev',
                             source_url=settings.SITE_URL)
            messages.success(request, _('Thank you for subscribing!'))
            return redirect('ecosystem.landing')
        except basket.BasketException:
            messages.error(request, _('We apologize, but an error '
                 'occurred in our system. Please try again later.'))

    return jingo.render(request, 'ecosystem/landing.html',
           {'videos': videos, 'newsletter_form': form})


def support(request):
    """Landing page for support."""
    return jingo.render(request, 'ecosystem/support.html',
           {'page': 'support', 'category': 'build'})


def installation(request):
    """Landing page for installation."""
    return jingo.render(request, 'ecosystem/installation.html',
           {'page': 'installation', 'category': 'publish'})


def documentation(request, page=None):
    """Page template for all content that is extracted from MDN's API."""
    _refresh_mdn(request)

    if not page:
        page = 'html5'

    locale = 'en-US'

    if request.LANG in locales:
        locale = request.LANG

    try:
        data = MdnCache.objects.get(name=page, locale=locale)
    except MdnCache.DoesNotExist:
        data = get_object_or_404(MdnCache, name=page, locale='en-US')

    if page in ('html5', 'manifests', 'manifest_faq', 'firefox_os',
                'devtools', 'templates', 'using_firefox_os_simulator'):
        category = 'build'
    elif page in ('principles', 'purpose', 'patterns', 'references',
                  'custom_elements'):
        category = 'design'
    else:
        category = 'publish'

    ctx = {
        'page': page,
        'title': data.title,
        'content': data.content,
        'category': category
    }

    return jingo.render(request, 'ecosystem/documentation.html', ctx)


def app_generator_documentation(request):
    """App Generator page."""

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

    ctx = {
        'page': 'app_generator',
        'title': _('App Generator'),
        'category': 'build',
        'app_generators': app_generators
    }

    return jingo.render(request, 'ecosystem/app_generator.html', ctx)


def apps_documentation(request, page=None):
    """Page template for all reference apps."""

    if page not in ('chrono', 'roller', 'face_value'):
        raise Http404

    third_party_libs = {
        'node': {
            'link': 'http://nodejs.org/',
            'title': _('Node.js')
        },
        'zepto': {
            'link': 'http://zeptojs.com/',
            'title': _('zepto.js')
        },
        'backbone': {
            'link': 'http://backbonejs.org/',
            'title': _('backbone.js')
        },
        'redis': {
            'link': 'http://redis.io',
            'title': _('redis')
        },
        'volo': {
            'link': 'http://volojs.org/',
            'title': 'volo.js'
        },
        'jquery': {
            'link': 'http://jquery.com/',
            'title': 'jQuery'
        },
        'requirejs': {
            'link': 'http://requirejs.org/',
            'title': 'RequireJS'
        }
    }

    web_api_libs = {
        'localstorage': {
            'link': '//developer.mozilla.org/docs/DOM/Storage#localStorage',
            'title': _('localStorage')
        },
        'appcache': {
            'link': '//developer.mozilla.org/docs/HTML/Using_the_application_cache',
            'title': _('appcache')
        },
        'open_web_apps': {
            'link': '//developer.mozilla.org/docs/Apps/Apps_JavaScript_API',
            'title': _('Open Web Apps')
        }
    }

    custom_elements_libs = {
        'gaia': {
            'link': 'https://wiki.mozilla.org/Gaia/Design/BuildingBlocks',
            'title': _('Gaia Building Blocks')
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


def firefox_os_simulator(request):
    """Landing page for Firefox OS Simulator."""

    ctx = {
        'page': 'firefox_os_simulator',
        'category': 'build'
    }

    return jingo.render(request, 'ecosystem/firefox_os_simulator.html', ctx)
