from jingo import register, env
from tower import ugettext as _

import jinja2
import json

from amo.helpers import url
from amo.urlresolvers import reverse
from amo.utils import JSONEncoder
from translations.helpers import truncate


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
def market_button(context, product):
    request = context['request']
    if product.is_webapp():
        classes = ['button', 'product']
        label = price_label(product)
        product_dict = product_as_dict(request, product)
        data_attrs = {
            'product': json.dumps(product_dict, cls=JSONEncoder),
            'manifestUrl': product.manifest_url,
        }
        if product.is_premium() and product.premium:
            classes.append('premium')
        if not product.is_premium():
            classes.append('install')
            label = _('Install')
        elif product.has_purchased(request.amo_user):
            classes.append('install purchased')
            label = _('Purchased')
        # TODO: Show inline BroswerID login popup for non-authenticated users.
        c = dict(product=product, label=label,
                 data_attrs=data_attrs, classes=' '.join(classes))
        t = env.get_template('site/helpers/webapp_button.html')
    return jinja2.Markup(t.render(c))


def product_as_dict(request, product):
    ret = {
        'id': product.id,
        'name': product.name,
        'manifestUrl': product.manifest_url,
        'preapprovalUrl': reverse('detail.purchase.preapproval',
                                  args=[product.app_slug]),
        'recordUrl': product.get_detail_url('record'),
        'author': product.listed_authors[0].name,
        'author_url': product.listed_authors[0].get_url_path(),
        'icon_128_url': product.get_icon_url(128)
    }
    if product.is_premium():
        ret.update({
            'price': product.premium.get_price() or '0',
            'priceLocale': product.premium.get_price_locale(),
            'purchase': product.get_purchase_url(),
        })
        if request.amo_user:
            ret['isPurchased'] = product.pk in request.amo_user.purchase_ids()
    return ret


@register.filter
@jinja2.contextfilter
def promo_slider(context, products):
    c = {
        'products': products
    }
    t = env.get_template('site/promo_slider.html')
    return jinja2.Markup(t.render(c))


@register.function
@jinja2.contextfunction
def mkt_breadcrumbs(context, product=None, items=None, crumb_size=40,
                    add_default=True):
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
        crumbs.append((url_, product.name))
    if items:
        crumbs.extend(items)

    if len(crumbs) == 1:
        crumbs = []

    crumbs = [(url_, truncate(label, crumb_size)) for (url_, label) in crumbs]
    t = env.get_template('site/helpers/breadcrumbs.html').render(
        breadcrumbs=crumbs)
    return jinja2.Markup(t)


@register.filter
def price_label(product):
    if product.is_premium() and product.premium:
        return product.premium.get_price_locale()
    return _('FREE')


@register.function
def form_field(field, label=None, tag='div', req=None, opt=False, hint=False,
               some_html=False, cc_startswith=None, cc_maxlength=None,
               grid=False, **attrs):
    c = dict(field=field, label=label, tag=tag, req=req, opt=opt, hint=hint,
             some_html=some_html, cc_startswith=cc_startswith,
             cc_maxlength=cc_maxlength, grid=grid, attrs=attrs)
    t = env.get_template('site/helpers/simple_field.html').render(**c)
    return jinja2.Markup(t)


@register.function
def grid_field(field, label=None, tag='div', req=None, opt=False, hint=False,
               some_html=False, cc_startswith=None, cc_maxlength=None,
               **attrs):
    return form_field(field, label, tag, req, opt, hint, some_html,
                      cc_startswith, cc_maxlength, grid=True, attrs=attrs)


@register.function
def admin_site_links():
    return {
        'addons': [
            ('Search for add-ons by name or id', url('zadmin.addon-search')),
            ('Featured add-ons', url('zadmin.features')),
            ('Monthly Pick', url('zadmin.monthly_pick')),
            ('Upgrade jetpack add-ons', url('zadmin.jetpack')),
            ('Name blocklist', url('zadmin.addon-name-blocklist')),
            ('Bulk add-on validation', url('zadmin.validation')),
            ('Fake mail', url('zadmin.mail')),
            ('Flagged reviews', url('zadmin.flagged')),
            ('ACR Reports', url('zadmin.compat')),
            ('Email Add-on Developers', url('zadmin.email_devs')),
        ],
        'settings': [
            ('View site settings', url('zadmin.settings')),
            ('Django admin pages', url('zadmin.home')),
            ('Site Events', url('zadmin.site_events')),
        ],
        'tools': [
            ('View request environment', url('amo.env')),
            ('Manage elasticsearch', url('zadmin.elastic')),
            ('View celery stats', url('zadmin.celery')),
            ('Purge data from memcache', url('zadmin.memcache')),
            ('Purge pages from zeus', url('zadmin.hera')),
            ('View graphite trends', url('amo.graphite', 'addons')),
            ('Create a new OAuth Consumer',
             url('zadmin.oauth-consumer-create')),
            ('Generate error', url('zadmin.generate-error')),
        ],
    }
