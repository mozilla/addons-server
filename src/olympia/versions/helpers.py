import jingo
import jinja2

from olympia.addons.helpers import new_context


@jingo.register.inclusion_tag('versions/version.html')
@jinja2.contextfunction
def version_detail(context, addon, version, src, impala=False,
                   skip_contrib=False, itemclass='item'):
    return new_context(**locals())


@jingo.register.inclusion_tag('versions/mobile/version.html')
@jinja2.contextfunction
def mobile_version_detail(context, addon, version, src):
    return new_context(**locals())


@jingo.register.filter
def nl2br_xhtml(string):
    """Turn newlines into <br/>."""
    if not string:
        return ''
    return jinja2.Markup('<br/>'.join(jinja2.escape(string).splitlines()))
