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


# page_type is used for setting the link 'sel' class (activity/purchases)
@register.function
def user_header(account, title, is_admin=False, page_type=''):
    t = env.get_template('lookup/helpers/user_header.html')
    return jinja2.Markup(t.render(account=account, title=title,
                                  is_admin=is_admin, page_type=page_type))


# page_type is used for setting the link 'sel' class
@register.function
def app_header(app, page_type=''):
    t = env.get_template('lookup/helpers/app_header.html')
    return jinja2.Markup(t.render(app=app, page_type=page_type))
