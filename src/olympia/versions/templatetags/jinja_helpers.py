import jinja2

from django_jinja import library

from olympia.addons.templatetags.jinja_helpers import new_context


@library.global_function
@library.render_with('versions/version.html')
@jinja2.contextfunction
def version_detail(
    context, addon, version, src, impala=False, itemclass='item'
):
    return new_context(**locals())
