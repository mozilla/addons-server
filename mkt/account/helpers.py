from jingo import register
import jinja2

from mkt.site.helpers import new_context
from mkt.account import forms


@register.inclusion_tag('account/helpers/refund_info.html')
@jinja2.contextfunction
def refund_info(context, product, contributions, show_link):
    return new_context(**locals())


@register.inclusion_tag('account/helpers/feedback_form.html')
@jinja2.contextfunction
def feedback_form(context, form=None):
    if not form:
        form = forms.FeedbackForm(None, request=context['request'])

    return new_context(**locals())
