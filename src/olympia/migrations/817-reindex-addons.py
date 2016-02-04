"""Reindex add-ons to fix stale data left by changes to the post_save
handler."""

from addons.cron import reindex_addons


reindex_addons()
