from django.db import models

import amo.models
import mkt


class AppSubmissionChecklist(amo.models.ModelBase):
    addon = models.OneToOneField('addons.Addon')
    terms = models.BooleanField()
    manifest = models.BooleanField()
    details = models.BooleanField()

    class Meta:
        db_table = 'submission_checklist_apps'

    def get_completed(self):
        """Return a list of completed submission steps."""
        completed = []
        for step, label in mkt.APP_STEPS:
            if getattr(self, step, False):
                completed.append(step)
        return completed

    def get_next(self):
        """Return the next step."""
        # Look through all the steps as defined in order and
        # see for each of the steps if they are completed or not.
        #
        # We don't care about done, plus there's no column for it.
        for step, label in mkt.APP_STEPS[:-1]:
            if not getattr(self, step, False):
                return step
