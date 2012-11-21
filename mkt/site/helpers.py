import json

from django.conf import settings

import caching.base as caching
import jinja2
import waffle
from jingo import register, env
from jingo_minify import helpers as jingo_minify_helpers
from tower import ugettext as _

import amo
from access import acl
from amo.helpers import urlparams
from amo.urlresolvers import reverse, get_outgoing_url
from amo.utils import JSONEncoder
from translations.helpers import truncate
from versions.compare import version_int as vint

import mkt


@jinja2.contextfunction
@register.function
def css(context, bundle, media=False, debug=None):
    if debug is None:
        debug = settings.TEMPLATE_DEBUG

    # ?debug=true gives you unminified CSS for testing on -dev/prod.
    if context['request'].GET.get('debug'):
        debug = True

    return jingo_minify_helpers.css(bundle, media, debug)


@jinja2.contextfunction
@register.function
def js(context, bundle, debug=None, defer=False, async=False):
    if debug is None:
        debug = settings.TEMPLATE_DEBUG

    # ?debug=true gives you unminified JS for testing on -dev/prod.
    if context['request'].GET.get('debug'):
        debug = True

    return jingo_minify_helpers.js(bundle, debug, defer, async)


@jinja2.contextfunction
@register.function
def get_media_hash(context):
    return jingo_minify_helpers.BUILD_ID_JS + jingo_minify_helpers.BUILD_ID_CSS


def new_context(context, **kw):
    c = dict(context.items())
    c.update(kw)
    return c


@register.function
def no_results():
    # This prints a "No results found" message. That's all. Carry on.
    t = env.get_template('site/helpers/no_results.html').render()
    return jinja2.Markup(t)


@jinja2.contextfunction
@register.function
def market_button(context, product, receipt_type=None, classes=None):
    request = context['request']
    if product.is_webapp():
        purchased = False
        classes = (classes or []) + ['button', 'product']
        data_attrs = {'manifest_url': product.get_manifest_url(),
                      'is_packaged': json.dumps(product.is_packaged)}

        # Handle premium apps.
        if product.is_premium() and product.premium:
            # User has purchased app.
            purchased = (request.amo_user and
                         product.pk in request.amo_user.purchase_ids())

            # App authors are able to install their apps free of charge.
            if (not purchased and
                    request.check_ownership(product, require_author=True)):
                purchased = True

        if purchased:
            label = _('Install')
        else:
            label = product.get_price()

        # Free apps and purchased apps get active install buttons.
        if not product.is_premium() or purchased:
            classes.append('install')

        c = dict(product=product, label=label, purchased=purchased,
                 data_attrs=data_attrs, classes=' '.join(classes))
        t = env.get_template('site/helpers/webapp_button.html')
    return jinja2.Markup(t.render(c))


def product_as_dict(request, product, purchased=None, receipt_type=None,
                    src=''):

    # Dev environments might not have authors set.
    author = ''
    author_url = ''
    if product.listed_authors:
        author = product.listed_authors[0].name
        author_url = product.listed_authors[0].get_url_path()

    url = (reverse('receipt.issue', args=[product.app_slug])
           if receipt_type else product.get_detail_url('record'))
    src = src or request.GET.get('src', '')

    ret = {
        'id': product.id,
        'name': product.name,
        'categories': [unicode(cat.name) for cat in
                       product.categories.all()],
        'manifest_url': product.get_manifest_url(),
        'preapprovalUrl': reverse('detail.purchase.preapproval',
                                  args=[product.app_slug]),
        'recordUrl': urlparams(url, src=src),
        'author': author,
        'author_url': author_url,
        'iconUrl': product.get_icon_url(64),
        'is_packaged': product.is_packaged,
        'src': src
    }

    # Add in previews to the dict.
    if product.all_previews:
        previews = []
        for p in product.all_previews:
            preview = {
                'fullUrl': jinja2.escape(p.image_url),
                'type': jinja2.escape(p.filetype),
                'thumbUrl': jinja2.escape(p.thumbnail_url),
                'caption': jinja2.escape(p.caption) if p.caption else ''
            }
            previews.append(preview)
        ret.update({'previews': previews})

    if product.is_premium() and product.premium:
        ret.update({
            'price': product.premium.get_price() or '0',
            'priceLocale': product.premium.get_price_locale(),
            'purchase': product.get_purchase_url(),
        })
        currencies = product.premium.supported_currencies()
        if len(currencies) > 1 and waffle.switch_is_active('currencies'):
            currencies_dict = dict([(k, v.get_price_locale())
                                    for k, v in currencies])
            ret['currencies'] = json.dumps(currencies_dict, cls=JSONEncoder)
        if request.amo_user:
            ret['isPurchased'] = purchased

    # Jinja2 escape everything except this whitelist so that bool is retained
    # for the JSON encoding.
    wl = ('isPurchased', 'price', 'currencies', 'categories', 'previews',
          'is_packaged')
    return dict([k, jinja2.escape(v) if k not in wl else v]
                for k, v in ret.items())


def product_as_dict_theme(request, product):
    # Dev environments might not have authors set.
    author = ''
    authors = product.persona.listed_authors
    if authors:
        author = authors[0].name

    ret = {
        'id': product.id,
        'name': product.name,
        'author': author,
        'previewUrl': product.persona.preview_url,
    }

    # Jinja2 escape everything except this whitelist so that bool is retained
    # for the JSON encoding.
    return dict([k, jinja2.escape(v)] for k, v in ret.items())


@jinja2.contextfunction
@register.function
def market_tile(context, product, link=True, src=''):
    request = context['request']
    if product.is_webapp():
        classes = []
        notices = []
        purchased = (request.amo_user and
                     product.pk in request.amo_user.purchase_ids())

        is_dev = product.has_author(request.amo_user)
        is_reviewer = acl.action_allowed(request, 'Apps', 'Review')
        receipt_type = 'developer' if is_dev or is_reviewer else None
        product_dict = product_as_dict(request, product, purchased=purchased,
                                       receipt_type=receipt_type, src=src)
        product_dict['prepareNavPay'] = reverse('webpay.prepare_pay',
                                                args=[product.app_slug])

        data_attrs = {
            'product': json.dumps(product_dict, cls=JSONEncoder),
            'manifest_url': product.get_manifest_url(),
            'src': src
        }

        ua = request.META.get('HTTP_USER_AGENT', '')
        need_firefox, need_upgrade = check_firefox(ua)

        if product.is_premium() and product.premium:
            classes.append('premium')

            if waffle.switch_is_active('disabled-payments'):
                notices.append(_('This app is temporarily unavailable for '
                                 'purchase.'))
            elif not request.GAIA:
                notices.append(_('This app is available for purchase on '
                                 'only Firefox OS.'))

        if product.is_packaged and not request.GAIA:
            notices.append(_('This app is available on only Firefox OS.'))

        if not request.MOBILE and product.device_types:
            url = reverse('ecosystem.installation')
            if product.device_types == [amo.DEVICE_DESKTOP]:
                classes.append('incompatible')
                # notices.append(
                #     _('Desktop support is temporarily disabled ('
                #       '<b data-href="{url}">learn more</b>).').format(url=url))
            elif amo.DEVICE_DESKTOP in product.device_types:
                classes.append('incompatible')
                # notices.append(
                #     _('Desktop support is temporarily disabled '
                #       '(<b data-href="{url}">learn more</b>). '
                #       'Please try this app in Firefox Mobile on your Android '
                #       'phone.').format(url=url))
            else:
                classes.append('incompatible')
                # notices.append(_('This is a mobile-only app. Please try this '
                #                  'app in Firefox Mobile on your Android '
                #                  'phone.'))

        if need_firefox:
            if request.MOBILE:
                classes.append('incompatible')
        elif need_upgrade:
            classes.append('incompatible')

        if notices or 'incompatible' in classes:
            classes += ['bad', 'disabled']

        c = dict(request=request, product=product, data_attrs=data_attrs,
                 classes=classes, link=link, notices=notices[:1])
        t = env.get_template('site/tiles/app.html')
        return jinja2.Markup(t.render(c))

    elif product.is_persona():
        classes = ['product', 'mkt-tile', 'arrow']
        product_dict = product_as_dict_theme(request, product)
        data_attrs = {
            'product': json.dumps(product_dict, cls=JSONEncoder),
            'src': src
        }
        c = dict(product=product, data_attrs=data_attrs,
                 classes=' '.join(classes), link=link)
        t = env.get_template('site/tiles/theme.html')
        return jinja2.Markup(t.render(c))


@register.filter
@jinja2.contextfilter
def promo_slider(context, products, feature=False):
    c = {
        'products': products,
        'feature': feature,
        'request': context['request'],
    }
    t = env.get_template('site/promo_slider.html')
    return jinja2.Markup(t.render(c))


@register.function
@jinja2.contextfunction
def mkt_breadcrumbs(context, product=None, items=None, crumb_size=40,
                    add_default=True, cls=None):
    """
    Wrapper function for ``breadcrumbs``.

    **items**
        list of [(url, label)] to be inserted after Add-on.
    **product**
        Adds the App/Add-on name to the end of the trail.  If items are
        specified then the App/Add-on will be linked.
    **add_default**
        Prepends trail back to home when True.  Default is False.
    """
    if add_default:
        crumbs = [(reverse('home'), _('Home'))]
    else:
        crumbs = []

    if product:
        if items:
            url_ = product.get_detail_url()
        else:
            # The Product is the end of the trail.
            url_ = None
        crumbs += [(reverse('browse.apps'), _('Apps')),
                   (url_, product.name)]
    if items:
        crumbs.extend(items)

    if len(crumbs) == 1:
        crumbs = []

    crumbs = [(url_, truncate(label, crumb_size)) for (url_, label) in crumbs]
    t = env.get_template('site/helpers/breadcrumbs.html').render(
        breadcrumbs=crumbs, cls=cls)
    return jinja2.Markup(t)


@register.function
def form_field(field, label=None, tag='div', req=None, opt=False, hint=False,
               tooltip=False, some_html=False, cc_startswith=None, cc_for=None,
               cc_maxlength=None, grid=False, cls=None, **attrs):
    c = dict(field=field, label=label or field.label, tag=tag, req=req,
             opt=opt, hint=hint, tooltip=tooltip, some_html=some_html,
             cc_startswith=cc_startswith, cc_for=cc_for,
             cc_maxlength=cc_maxlength, grid=grid, cls=cls, attrs=attrs)
    t = env.get_template('site/helpers/simple_field.html').render(**c)
    return jinja2.Markup(t)


@register.function
def grid_field(field, label=None, tag='div', req=None, opt=False, hint=False,
               some_html=False, cc_startswith=None, cc_maxlength=None,
               **attrs):
    return form_field(field, label, tag, req, opt, hint, some_html,
                      cc_startswith, cc_maxlength, grid=True, attrs=attrs)


@register.filter
@jinja2.contextfilter
def timelabel(context, time):
    t = env.get_template('site/helpers/timelabel.html').render(time=time)
    return jinja2.Markup(t)


@register.function
def admin_site_links():
    return {
        'addons': [
            ('Search for apps by name or id', reverse('zadmin.addon-search')),
            ('Featured apps', reverse('zadmin.featured_apps')),
            ('Fake mail', reverse('zadmin.mail')),
            ('Flagged reviews', reverse('zadmin.flagged')),
        ],
        'users': [
            ('Configure groups', reverse('admin:access_group_changelist')),
        ],
        'settings': [
            ('View site settings', reverse('zadmin.settings')),
            ('Django admin pages', reverse('zadmin.home')),
            ('Site Events', reverse('zadmin.site_events')),
        ],
        'tools': [
            ('View request environment', reverse('amo.env')),
            ('Manage elasticsearch', reverse('zadmin.elastic')),
            ('Manage EcoSystem', reverse('mkt.zadmin.ecosystem')),
            ('Purge data from memcache', reverse('zadmin.memcache')),
            ('Purge pages from zeus', reverse('zadmin.hera')),
            ('Create a new OAuth Consumer',
             reverse('zadmin.oauth-consumer-create')),
            ('Generate error', reverse('zadmin.generate-error')),
            ('Site Status', reverse('amo.monitor')),
            ('Force Manifest Re-validation',
             reverse('zadmin.manifest_revalidation'))
        ],
    }


@register.filter
def external_href(url):
    t = 'target="_blank" href="%s"' % get_outgoing_url(unicode(url))
    return jinja2.Markup(t)


@register.function
@jinja2.contextfunction
def get_login_link(context, to=None):
    request = context['request']
    # If to is given use that, otherwise get from request.
    to = to or request.GET.get('to')

    # If logged in, just return the URL.
    if request.user.is_authenticated():
        return to

    url = reverse('users.login')
    # Don't allow loop backs to login.
    if to == url:
        to = None
    return urlparams(url, to=to)


@register.function
def check_firefox(ua):
    return caching.cached(lambda: _check_firefox(ua), 'check_firefox:%s' % ua)


def _check_firefox(ua):
    need_firefox, need_upgrade = True, True

    for ua_res, min_version in mkt.platforms.APP_PLATFORMS:
        for ua_re in ua_res:
            match = ua_re.search(ua)
            if match:
                v = match.groups()[0]

                # If we found a version at all, then this is Firefox.
                need_firefox = False

                # If we found a matching version, then we can install apps!
                need_upgrade = vint(v) < min_version

    return need_firefox, need_upgrade


@register.filter
def more_button(pager):
    t = env.get_template('site/paginator.html')
    return jinja2.Markup(t.render(pager=pager))


@register.function
@jinja2.contextfunction
def allow_installs(context):
    """
    This will return of a boolean of whether we're on a version of
    Firefox that supports `navigator.mozApps`.
    """
    ua = context['request'].META.get('HTTP_USER_AGENT', '')
    return check_firefox(ua) == (False, False)
