from tower import ugettext_lazy as _

# Theme review queue constants.
THEME_INITIAL_LOCKS = 5  # Initial number of themes to check out.
THEME_MAX_LOCKS = 20  # Max amount of themes to check out per reviewer.
THEME_LOCK_EXPIRY = 30  # Minutes.

ACTION_MOREINFO = 0
ACTION_FLAG = 1
ACTION_DUPLICATE = 2
ACTION_REJECT = 3
ACTION_APPROVE = 4
REVIEW_ACTIONS = {
    ACTION_MOREINFO: _('Request More Info'),
    ACTION_FLAG: _('Flag'),
    ACTION_DUPLICATE: _('Duplicate'),
    ACTION_REJECT: _('Reject'),
    ACTION_APPROVE: _('Approve')
}

THEME_REJECT_REASONS = {
    0: _('Other rejection reason'),
    1: _('Sexual or pornographic content'),
    2: _('Inappropriate or offensive content'),
    3: _('Violence, war, or weaponry images'),
    4: _('Nazi or other hate content'),
    5: _('Defamatory content'),
    6: _('Online gambling'),
    7: _('Spam content'),
    8: _('Low-quality, stretched, or blank image'),
    9: _('Header image alignment problem'),
}
