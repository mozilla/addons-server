def match_rules(rules, app, action):
    """
    This will match rules found in Group.
    """

    for rule in rules.split(','):
        (rule_app, rule_action) = rule.split(':')

        if rule_app == '*' or rule_app == app:
            if (rule_action == '*'
                or rule_action == action
                or action == '%'):
                return True

    return False


def action_allowed(request, app, action):
    """
    Determines if a user has permission to do a certain action

    'Admin:%' is true if the user has any of:
    ('Admin:*', 'Admin:%s'%whatever, '*:*',) as rules.
    """

    return any(match_rules(group.rules, app, action)
        for group in request.groups)
