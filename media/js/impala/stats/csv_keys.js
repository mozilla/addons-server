var csv_keys = {
    downloads: {
        "count": gettext('Downloads')
    },
    usage: {
        "count": gettext('Daily Users')
    },
    sources: {
        "null"                  : gettext('Unknown'),
        'api'                   : gettext('Add-ons Manager'),
        'search'                : gettext('Search Results'),
        'homepagepromo'         : gettext('Homepage Promo'),
        'hp-btn-promo'          : gettext('Homepage Promo'),
        'hp-dl-promo'           : gettext('Homepage Promo'),
        'hp-hc-featured'        : gettext('Homepage Featured'),
        'hp-dl-featured'        : gettext('Homepage Featured'),
        'hp-hc-upandcoming'     : gettext('Homepage Up and Coming'),
        'hp-dl-upandcoming'     : gettext('Homepage Up and Coming'),
        'hp-dl-mostpopular'     : gettext('Homepage Most Popular'),
        'dp-btn-primary'        : gettext('Detail Page'),
        'dp-btn-version'        : gettext('Detail Page (bottom)'),
        'addondetail'           : gettext('Detail Page'),
        'addon-detail-version'  : gettext('Detail Page (bottom)'),
        'dp-btn-devchannel'     : gettext('Detail Page (Development Channel)'),
        'oftenusedwith'         : gettext('Often Used With'),
        'dp-hc-oftenusedwith'   : gettext('Often Used With'),
        'dp-dl-oftenusedwith'   : gettext('Often Used With'),
        'dp-hc-othersby'        : gettext('Others By Author'),
        'dp-dl-othersby'        : gettext('Others By Author'),
        'dp-hc-dependencies'    : gettext('Dependencies'),
        'dp-dl-dependencies'    : gettext('Dependencies'),
        'dp-hc-upsell'          : gettext('Upsell'),
        'dp-dl-upsell'          : gettext('Upsell'),

        'sharingapi'            : gettext('Sharing'),
        'category'              : gettext('Category Pages'),
        'collection'            : gettext('Collections'),
        'cb-hc-featured'        : gettext('Category Landing Featured Carousel'),
        'cb-dl-featured'        : gettext('Category Landing Featured Carousel'),
        'cb-hc-toprated'        : gettext('Category Landing Top Rated'),
        'cb-dl-toprated'        : gettext('Category Landing Top Rated'),
        'cb-hc-mostpopular'     : gettext('Category Landing Most Popular'),
        'cb-dl-mostpopular'     : gettext('Category Landing Most Popular'),
        'cb-hc-recentlyadded'   : gettext('Category Landing Recently Added'),
        'cb-dl-recentlyadded'   : gettext('Category Landing Recently Added'),
        'cb-btn-featured'       : gettext('Browse Listing Featured Sort'),
        'cb-dl-featured'        : gettext('Browse Listing Featured Sort'),
        'cb-btn-users'          : gettext('Browse Listing Users Sort'),
        'cb-dl-users'           : gettext('Browse Listing Users Sort'),
        'cb-btn-rating'         : gettext('Browse Listing Rating Sort'),
        'cb-dl-rating'          : gettext('Browse Listing Rating Sort'),
        'cb-btn-created'        : gettext('Browse Listing Created Sort'),
        'cb-dl-created'         : gettext('Browse Listing Created Sort'),
        'cb-btn-name'           : gettext('Browse Listing Name Sort'),
        'cb-dl-name'            : gettext('Browse Listing Name Sort'),
        'cb-btn-popular'        : gettext('Browse Listing Popular Sort'),
        'cb-dl-popular'         : gettext('Browse Listing Popular Sort'),
        'cb-btn-updated'        : gettext('Browse Listing Updated Sort'),
        'cb-dl-updated'         : gettext('Browse Listing Updated Sort'),
        'cb-btn-hotness'        : gettext('Browse Listing Up and Coming Sort'),
        'cb-dl-hotness'         : gettext('Browse Listing Up and Coming Sort')
    },
    contributions: {
        "count": gettext('Number of Contributions'),
        "total": gettext('Total Amount Contributed'),
        "average": gettext('Average Contribution')
    },
    overview: {
        'downloads' : gettext('Downloads'),
        'updates'   : gettext('Daily Users')
    },
    apps : {
        '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}' : gettext('Firefox'),
        '{86c18b42-e466-45a9-ae7a-9b95ba6f5640}' : gettext('Mozilla'),
        '{3550f703-e582-4d05-9a08-453d09bdfdc6}' : gettext('Thunderbird'),
        '{718e30fb-e89b-41dd-9da7-e25a45638b28}' : gettext('Sunbird'),
        '{92650c4d-4b8e-4d2a-b7eb-24ecf4f6b63a}' : gettext('SeaMonkey'),
        '{a23983c0-fd0e-11dc-95ff-0800200c9a66}' : gettext('Fennec')
    },
    chartTitle: {
        "overview"  : [
            gettext("Downloads and Daily Users, last {0}"),
            gettext("Downloads and Daily Users from {0} to {1}")
        ],
        "downloads" : [
            gettext("Downloads, last {0}"),
            gettext("Downloads from {0} to {1}")
        ],
        "usage"  : [
            gettext("Daily Users, last {0}"),
            gettext("Daily Users from {0} to {1}")
        ],
        "apps"  : [
            gettext("Applications, last {0}"),
            gettext("Applications from {0} to {1}")
        ],
        "os"  : [
            gettext("Platforms, last {0}"),
            gettext("Platforms from {0} to {1}")
        ],
        "locales"  : [
            gettext("Languages, last {0}"),
            gettext("Languages from {0} to {1}")
        ],
        "versions"  : [
            gettext("Add-on Versions, last {0}"),
            gettext("Add-on Versions from {0} to {1}")
        ],
        "statuses"  : [
            gettext("Add-on Status, last {0}"),
            gettext("Add-on Status from {0} to {1}")
        ],
        "sources"  : [
            gettext("Download Sources, last {0}"),
            gettext("Download Sources from {0} to {1}")
        ],
        "contributions"  : [
            gettext("Contributions, last {0}"),
            gettext("Contributions from {0} to {1}")
        ]
    },
    aggregateLabel: {
        "downloads" : gettext("<b>{0}</b> downloads from {1} to {2}"),
        "usage"     : gettext("<b>{0}</b> users from {1} to {2}")
    }
};
