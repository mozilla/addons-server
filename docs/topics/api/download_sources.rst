================
Download Sources
================

.. _download-sources:

When requesting an add-on file URL, clients have the option to indicate what is
the source of the request. This will then be used to group by downloads by
sources in the add-on statistics page.

To indicate the source, add the ``src`` query parameter to the download URL.
The following values are recognized:

.. csv-table::
   :header: "Name", "Description"

    api,"Add-ons Manager"
    discovery-promo,"Add-ons Manager Promo"
    discovery-featured,"Add-ons Manager Featured"
    discovery-learnmore,"Add-ons Manager Learn More"
    ss,"Search Suggestions"
    search,"Search Results"
    homepagepromo,"Homepage Promo"
    hp-btn-promo,"Homepage Promo"
    hp-dl-promo,"Homepage Promo"
    hp-hc-featured,"Homepage Featured"
    hp-dl-featured,"Homepage Featured"
    hp-hc-upandcoming,"Homepage Up and Coming"
    hp-dl-upandcoming,"Homepage Up and Coming"
    hp-dl-mostpopular,"Homepage Most Popular"
    dp-btn-primary,"Detail Page"
    dp-btn-version,"Detail Page (bottom)"
    addondetail,"Detail Page"
    addon-detail-version,"Detail Page (bottom)"
    dp-btn-devchannel,"Detail Page (Development Channel)"
    oftenusedwith,"Often Used With"
    dp-hc-oftenusedwith,"Often Used With"
    dp-dl-oftenusedwith,"Often Used With"
    dp-hc-othersby,"Others By Author"
    dp-dl-othersby,"Others By Author"
    dp-hc-dependencies,"Dependencies"
    dp-dl-dependencies,"Dependencies"
    dp-hc-upsell,"Upsell"
    dp-dl-upsell,"Upsell"
    developers,"Meet the Developer"
    userprofile,"User Profile"
    version-history,"Version History"
    sharingapi,"Sharing"
    category,"Category Pages"
    collection,"Collections"
    cb-hc-featured,"Category Landing Featured Carousel"
    cb-dl-featured,"Category Landing Featured Carousel"
    cb-hc-toprated,"Category Landing Top Rated"
    cb-dl-toprated,"Category Landing Top Rated"
    cb-hc-mostpopular,"Category Landing Most Popular"
    cb-dl-mostpopular,"Category Landing Most Popular"
    cb-hc-recentlyadded,"Category Landing Recently Added"
    cb-dl-recentlyadded,"Category Landing Recently Added"
    cb-btn-featured,"Browse Listing Featured Sort"
    cb-dl-featured,"Browse Listing Featured Sort"
    cb-btn-users,"Browse Listing Users Sort"
    cb-dl-users,"Browse Listing Users Sort"
    cb-btn-rating,"Browse Listing Rating Sort"
    cb-dl-rating,"Browse Listing Rating Sort"
    cb-btn-created,"Browse Listing Created Sort"
    cb-dl-created,"Browse Listing Created Sort"
    cb-btn-name,"Browse Listing Name Sort"
    cb-dl-name,"Browse Listing Name Sort"
    cb-btn-popular,"Browse Listing Popular Sort"
    cb-dl-popular,"Browse Listing Popular Sort"
    cb-btn-updated,"Browse Listing Updated Sort"
    cb-dl-updated,"Browse Listing Updated Sort"
    cb-btn-hotness,"Browse Listing Up and Coming Sort"
    cb-dl-hotness,"Browse Listing Up and Coming Sort"
    find-replacement,"Find replacement service for obsolete add-ons"
