from django import template

from olympia.constants.abuse import DECISION_ACTIONS


register = template.Library()


@register.filter
def decision_action_label(action):
    return DECISION_ACTIONS(action).label
