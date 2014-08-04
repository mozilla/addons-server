-- Remove point types that only apply to Marketplace
DELETE
    FROM reviewer_scores
    WHERE note_key IN (70, 71, 72, 73, 81);

-- Remove temporary manual point adjustments for Marketplace reviews
DELETE
    FROM reviewer_scores
    WHERE
        note_key = 0 AND
        note LIKE '% remove app review points';
