from jingo import register, env
import jinja2


@register.function
def form_field(field, label=None, tag='div', req=None, hint=False, **attrs):
    c = dict(field=field, label=label, tag=tag, req=req, hint=hint,
             attrs=attrs)
    t = env.get_template('site/helpers/simple_field.html').render(**c)
    return jinja2.Markup(t)
