from django.utils.translation import ugettext_lazy as _

# Review queue pagination
REVIEWS_PER_PAGE = 200
REVIEWS_PER_PAGE_MAX = 400

# Theme review queue constants.
THEME_INITIAL_LOCKS = 5  # Initial number of themes to check out.
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
    # 0: _('Other rejection reason'),
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


WOULD_NOT_HAVE_BEEN_AUTO_APPROVED = 0
WOULD_HAVE_BEEN_AUTO_APPROVED = 1
AUTO_APPROVED = 2
NOT_AUTO_APPROVED = 3

AUTO_APPROVAL_VERDICT_CHOICES = (
    (WOULD_NOT_HAVE_BEEN_AUTO_APPROVED,
        'Would have been auto-approved (dry-run mode was in effect)'),
    (WOULD_HAVE_BEEN_AUTO_APPROVED,
        'Would *not* have been auto-approved (dry-run mode was in effect)'),
    (AUTO_APPROVED, 'Was auto-approved'),
    (NOT_AUTO_APPROVED, 'Was *not* auto-approved'),
)
