UPDATE bldetails INNER JOIN blitems ON bldetails.id=blitems.details_id
    SET bldetails.created=blitems.created;

UPDATE bldetails INNER JOIN blplugins ON bldetails.id=blplugins.details_id
    SET bldetails.created=blplugins.created;

UPDATE bldetails INNER JOIN blgfxdrivers ON bldetails.id=blgfxdrivers.details_id
    SET bldetails.created=blgfxdrivers.created;
