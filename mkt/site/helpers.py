from jingo import register, env
import jinja2

from amo.helpers import url


@register.function
def form_field(field, label=None, tag='div', req=None, hint=False,
               some_html=False, cc_startswith=None, cc_maxlength=None,
               **attrs):
    c = dict(field=field, label=label, tag=tag, req=req, hint=hint,
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
        ],
    }
