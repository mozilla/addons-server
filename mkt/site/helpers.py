from jingo import register, env
import jinja2


@register.function
def form_field(field, label=None, tag=None, req=None, **attrs):
    c = dict(field=field, label=label, tag=tag, req=req, attrs=attrs)
    t = env.get_template('site/helpers/simple_field.html').render(**c)
    return jinja2.Markup(t)
