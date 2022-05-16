from django.db import models
from django.utils import timezone


class ReindexingManager(models.Manager):
    """Used to flag when an elasticsearch reindexing is occurring."""

    def flag_reindexing(self, new_index, old_index, alias):
        """Flag the database for a reindex"""
        if self.is_reindexing():
            return  # Already flagged.

        return self.create(new_index=new_index, old_index=old_index, alias=alias)

    def unflag_reindexing(self):
        """Unflag the database for a reindex."""
        self.all().delete()

    def is_reindexing(self):
        """Return True if a reindexing is occurring."""
        return self.all().exists()

    def get_indices(self, index):
        """Return the indices associated with an alias.

        If we are reindexing, there should be two indices returned.
        """
        try:
            # Can we find a reindex for the given alias/index ?
            reindex = self.get(alias=index)
            # Yes. Let's return both new and old indexes.
            return [
                idx for idx in (reindex.new_index, reindex.old_index) if idx is not None
            ]
        except Reindexing.DoesNotExist:
            return [index]


class Reindexing(models.Model):
    start_date = models.DateTimeField(default=timezone.now)
    old_index = models.CharField(max_length=255, null=True)
    new_index = models.CharField(max_length=255)
    alias = models.CharField(max_length=255)

    objects = ReindexingManager()

    class Meta:
        db_table = 'zadmin_reindexing'
