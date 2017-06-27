import jingo
import jinja2

from olympia.addons.templatetags.jinja_helpers import new_context


@jingo.register.inclusion_tag('versions/version.html')
@jinja2.contextfunction
def version_detail(context, addon, version, src, impala=False,
                   skip_contrib=False, itemclass='item'):
    return new_context(**locals())
