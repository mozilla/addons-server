UPDATE
    reviewer_scores AS rs,
    addons AS a
SET
    rs.note_key = 81 -- REVIEW_APP_REVIEW
WHERE
    rs.note_key = 80 -- REVIEW_ADDON_REVIEW
    AND a.id = rs.addon_id
    AND a.addontype_id = 11 -- ADDON_WEBAPP
;
