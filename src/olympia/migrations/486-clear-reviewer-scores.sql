-- Clearing reviewer scores since they're not on prod and the note_key changed.
DELETE FROM reviewer_scores;
