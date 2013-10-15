import json
import os

from django.conf import settings

import commonware.log
import jinja2
from jingo import env, register
from jingo_minify import helpers as jingo_minify_helpers
from tower import ugettext as _

from amo.helpers import urlparams
from amo.urlresolvers import get_outgoing_url, reverse
from translations.helpers import truncate

log = commonware.log.getLogger('z.mkt.site')


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
        reviewer = receipt_type == 'reviewer'
        data_attrs = {'manifest_url': product.get_manifest_url(reviewer),
                      'is_packaged': json.dumps(product.is_packaged)}

        installed = None

        if request.amo_user:
            installed_set = request.amo_user.installed_set
            installed = installed_set.filter(addon=product).exists()

        # Handle premium apps.
        if product.has_premium():
            # User has purchased app.
            purchased = (request.amo_user and
                         product.pk in request.amo_user.purchase_ids())

            # App authors are able to install their apps free of charge.
            if (not purchased and
                    request.check_ownership(product, require_author=True)):
                purchased = True

        if installed or purchased or not product.has_premium():
            label = _('Install')
        else:
            label = product.get_tier_name()

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
    reviewer = receipt_type == 'reviewer'

    ret = {
        'id': product.id,
        'name': product.name,
        'categories': [unicode(cat.slug) for cat in
                       product.categories.all()],
        'manifest_url': product.get_manifest_url(reviewer),
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

    if product.premium:
        ret.update({
            'price': product.get_price(region=request.REGION.id),
            'priceLocale': product.get_price_locale(region=request.REGION.id),
        })

        if request.amo_user:
            ret['isPurchased'] = purchased

    # Jinja2 escape everything except this whitelist so that bool is retained
    # for the JSON encoding.
    wl = ('categories', 'currencies', 'isPurchased', 'is_packaged', 'previews',
          'price', 'priceLocale')
    return dict([k, jinja2.escape(v) if k not in wl else v]
                for k, v in ret.items())


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
        Prepends trail back to home when True.  Default is True.
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
        crumbs += [(None, _('Apps')), (url_, product.name)]
    if items:
        crumbs.extend(items)

    if len(crumbs) == 1:
        crumbs = []

    crumbs = [(u, truncate(label, crumb_size)) for (u, label) in crumbs]
    t = env.get_template('site/helpers/breadcrumbs.html').render(
        breadcrumbs=crumbs, cls=cls)
    return jinja2.Markup(t)


@register.function
def form_field(field, label=None, tag='div', req=None, opt=False, hint=False,
               tooltip=False, some_html=False, cc_startswith=None, cc_for=None,
               cc_maxlength=None, grid=False, cls=None, validate=False):
    attrs = {}
    # Add a `required` attribute so we can do form validation.
    # TODO(cvan): Write tests for kumar some day.
    if validate and field.field.required:
        attrs['required'] = ''
    c = dict(field=field, label=label or field.label, tag=tag, req=req,
             opt=opt, hint=hint, tooltip=tooltip, some_html=some_html,
             cc_startswith=cc_startswith, cc_for=cc_for,
             cc_maxlength=cc_maxlength, grid=grid, cls=cls, attrs=attrs)
    t = env.get_template('site/helpers/simple_field.html').render(**c)
    return jinja2.Markup(t)


@register.function
def grid_field(field, label=None, tag='div', req=None, opt=False, hint=False,
               some_html=False, cc_startswith=None, cc_maxlength=None,
               validate=False):
    return form_field(field, label, tag, req, opt, hint, some_html,
                      cc_startswith, cc_maxlength, grid=True,
                      validate=validate)


@register.filter
@jinja2.contextfilter
def timelabel(context, time):
    t = env.get_template('site/helpers/timelabel.html').render(time=time)
    return jinja2.Markup(t)


@register.function
def mkt_admin_site_links():
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


@register.filter
def more_button(pager):
    t = env.get_template('site/paginator.html')
    return jinja2.Markup(t.render(pager=pager))


@register.function
@jinja2.contextfunction
def dev_agreement(context):
    lang = context['request'].LANG
    if lang in settings.AMO_LANGUAGES:
        try:
            template = env.get_template('dev-agreement/%s.html' % lang)
        except jinja2.TemplateNotFound:
            pass
        else:
            return jinja2.Markup(template.render())
    template = env.get_template('dev-agreement/en-US.html')
    return jinja2.Markup(template.render())
