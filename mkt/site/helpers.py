from jingo import register, env
from tower import ugettext as _

import jinja2

from amo.helpers import url


@register.function
def market_button(product):
    if product.is_webapp():
        classes = ['button']
        label = price_label(product)
        if (product.is_premium):
            classes.append('premium')
            data_attrs = {
                # 'purchase': product.get_detail_url('purchase') + '?',
                # 'start-purchase': product.get_detail_url('pruchase.start'),
                'cost': product.premium.get_price(),
            }
        if ((product.is_premium() and product.has_purchased(amo_user)) or
            (not product.is_premium())):
            classes.append('install')
            label = _('Install App')
            data_attrs.update( {'manifest-url': product.manifest_url} )
        c = dict(product=product, label=label,
                 data_attrs=data_attrs, classes=' '.join(classes))
        t = env.get_template('mkt/webapp_button.html')
    return jinja2.Markup(t.render(c))


def price_label(product):
    if product.is_premium:
        return product.premium.get_price_locale()
    return _('FREE')


@register.function
def form_field(field, label=None, tag='div', req=None, opt=False, hint=False,
               some_html=False, cc_startswith=None, cc_maxlength=None,
               **attrs):
    c = dict(field=field, label=label, tag=tag, req=req, opt=opt, hint=hint,
             some_html=some_html, cc_startswith=cc_startswith,
             cc_maxlength=cc_maxlength, attrs=attrs)
    t = env.get_template('site/helpers/simple_field.html').render(**c)
    return jinja2.Markup(t)


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
