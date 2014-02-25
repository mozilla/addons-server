from jingo import env, register
import jinja2

from access import acl


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
@jinja2.contextfunction
def app_header(context, app, page_type=''):
    t = env.get_template('lookup/helpers/app_header.html')

    is_author = acl.check_ownership(context['request'], app)
    is_operator = any(g.name == 'Operators' for g in context['request'].groups)
    is_admin = acl.action_allowed(context['request'], 'Users', 'Edit')
    is_staff = acl.action_allowed(context['request'], 'Apps', 'Configure')
    is_reviewer = acl.check_reviewer(context['request'])
    return jinja2.Markup(t.render(app=app, page_type=page_type,
                                  is_admin=is_admin, is_staff=is_staff,
                                  is_reviewer=is_reviewer, is_author=is_author,
                                  is_operator=is_operator))


@register.function
@jinja2.contextfunction
def is_operator(context):
    return any(g.name == 'Operators' for g in context['request'].groups)
