from django.db import models
from django.utils import timezone


class ReindexingManager(models.Manager):
    """Used to flag when an elasticsearch reindexing is occurring."""

    def _flag_reindexing(self, site, new_index, old_index, alias):
        """Flag the database for a reindex on the given site."""
        if self._is_reindexing(site):
            return  # Already flagged.

        return self.create(new_index=new_index,
                           old_index=old_index,
                           alias=alias,
                           site=site)

    def flag_reindexing_amo(self, new_index, old_index, alias):
        """Flag the database for an AMO reindex."""
        return self._flag_reindexing('amo', new_index, old_index, alias)

    def _unflag_reindexing(self, site):
        """Unflag the database for a reindex on the given site."""
        self.filter(site=site).delete()

    def unflag_reindexing_amo(self):
        """Unflag the database for an AMO reindex."""
        self._unflag_reindexing('amo')

    def _is_reindexing(self, site):
        """Return True if a reindexing is occurring for the given site."""
        return self.filter(site=site).exists()

    def is_reindexing_amo(self):
        """Return True if a reindexing is occurring on AMO."""
        return self._is_reindexing('amo')

    def get_indices(self, index):
        """Return the indices associated with an alias.

        If we are reindexing, there should be two indices returned.

        """
        try:
            reindex = self.get(alias=index)
            # Yes. Let's reindex on both indexes.
            return [idx for idx in (reindex.new_index, reindex.old_index)
                    if idx is not None]
        except Reindexing.DoesNotExist:
            return [index]


class Reindexing(models.Model):
    SITE_CHOICES = (
        ('amo', 'AMO'),
    )
    start_date = models.DateTimeField(default=timezone.now)
    old_index = models.CharField(max_length=255, null=True)
    new_index = models.CharField(max_length=255)
    alias = models.CharField(max_length=255)
    site = models.CharField(max_length=3, choices=SITE_CHOICES)

    objects = ReindexingManager()

    class Meta:
        db_table = 'zadmin_reindexing'
