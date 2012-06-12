from jingo import env, register
import jinja2


@register.filter
@jinja2.contextfilter
def format_currencies(context, currencies):
    cs = ', '.join(['%s %.2f' % (code, amount)
                    for code, amount in currencies.items()
                    if amount > 0.0])
    if cs:
        cs = '(%s)' % cs
    return jinja2.Markup(cs)


@register.function
def lookup_header(account, title):
    t = env.get_template('acct_lookup/helpers/lookup_header.html')
    return jinja2.Markup(t.render(account=account, title=title))
