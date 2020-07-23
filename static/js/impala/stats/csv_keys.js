var csv_keys = {
    downloads: {
        "count": gettext('Downloads')
    },
    usage: {
        "count": gettext('Daily Users')
    },
    collections_created: {
        'count': gettext('Collections Created')
    },
    addons_in_use: {
        'count': gettext('Add-ons in Use')
    },
    addons_created: {
        'count': gettext('Add-ons Created')
    },
    addons_downloaded: {
        'count': gettext('Add-ons Downloaded')
    },
    addons_updated: {
        'count': gettext('Add-ons Updated')
    },
    reviews_created: {
        'count': gettext('Reviews Written')
    },
    users_created: {
        'count': gettext('User Signups')
    },
    subscribers: {
        'count': gettext('Subscribers')
    },
    ratings: {
        'count': gettext('Ratings')
    },
    sales: {
        'count': gettext('Sales')
    },
    installs: {
        'count': gettext('Installs')
    },
    sources: {
        "null"                  : gettext('Unknown'),
        'api'                   : gettext('Add-ons Manager'),
        'discovery-promo'       : gettext('Add-ons Manager Promo'),
        'discovery-featured'    : gettext('Add-ons Manager Featured'),
        'discovery-learnmore'   : gettext('Add-ons Manager Learn More'),
        'ss'                    : gettext('Search Suggestions'),
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
        'developers'            : gettext('Meet the Developer'),
        'userprofile'           : gettext('User Profile'),
        'version-history'       : gettext('Version History'),

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
    app_overview: {
        'installs': gettext('Installs'),
        'sales': gettext('Sales'),
        'usage': gettext('Usage')
    },
    apps : {
        '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}' : gettext('Firefox'),
        '{86c18b42-e466-45a9-ae7a-9b95ba6f5640}' : gettext('Mozilla'),
        '{3550f703-e582-4d05-9a08-453d09bdfdc6}' : gettext('Thunderbird'),
        '{718e30fb-e89b-41dd-9da7-e25a45638b28}' : gettext('Sunbird'),
        '{92650c4d-4b8e-4d2a-b7eb-24ecf4f6b63a}' : gettext('SeaMonkey'),
        '{a23983c0-fd0e-11dc-95ff-0800200c9a66}' : gettext('Fennec'),
        '{aa3c5121-dab2-40e2-81ca-7ea25febc110}' : gettext('Android')
    },
    chartTitle: {
        "overview"  : [
            // L10n: {0} is an integer.
            gettext("Downloads and Daily Users, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Downloads and Daily Users from {0} to {1}")
        ],
        "app_overview"  : [
            // L10n: {0} is an integer.
            gettext("Installs and Daily Users, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Installs and Daily Users from {0} to {1}")
        ],
        "downloads" : [
            // L10n: {0} is an integer.
            gettext("Downloads, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Downloads from {0} to {1}")
        ],
        "usage"  : [
            // L10n: {0} is an integer.
            gettext("Daily Users, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Daily Users from {0} to {1}")
        ],
        "apps"  : [
            // L10n: {0} is an integer.
            gettext("Applications, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Applications from {0} to {1}")
        ],
        "countries"  : [
            // L10n: {0} is an integer.
            gettext("Countries, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Countries from {0} to {1}")
        ],
        "os"  : [
            // L10n: {0} is an integer.
            gettext("Platforms, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Platforms from {0} to {1}")
        ],
        "locales"  : [
            // L10n: {0} is an integer.
            gettext("Languages, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Languages from {0} to {1}")
        ],
        "versions"  : [
            // L10n: {0} is an integer.
            gettext("Add-on Versions, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Add-on Versions from {0} to {1}")
        ],
        "statuses"  : [
            // L10n: {0} is an integer.
            gettext("Add-on Status, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Add-on Status from {0} to {1}")
        ],
        "sources"  : [
            // L10n: {0} is an integer.
            gettext("Download Sources, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Download Sources from {0} to {1}")
        ],
        "mediums"  : [
            // L10n: {0} is an integer.
            gettext("Download Mediums, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Download Mediums from {0} to {1}")
        ],
        "contents"  : [
            // L10n: {0} is an integer.
            gettext("Download Contents, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Download Contents from {0} to {1}")
        ],
        "campaigns"  : [
            // L10n: {0} is an integer.
            gettext("Download Campaigns, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Download Campaigns from {0} to {1}")
        ],
        "contributions"  : [
            // L10n: {0} is an integer.
            gettext("Contributions, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Contributions from {0} to {1}")
        ],
        "site"  : [
            // L10n: {0} is an integer.
            gettext("Site Metrics, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Site Metrics from {0} to {1}")
        ],
        "addons_in_use" : [
            // L10n: {0} is an integer.
            gettext("Add-ons in Use, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Add-ons in Use from {0} to {1}")
        ],
        "addons_downloaded" : [
            // L10n: {0} is an integer.
            gettext("Add-ons Downloaded, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Add-ons Downloaded from {0} to {1}")
        ],
        "addons_created" : [
            // L10n: {0} is an integer.
            gettext("Add-ons Created, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Add-ons Created from {0} to {1}")
        ],
        "addons_updated" : [
            // L10n: {0} is an integer.
            gettext("Add-ons Updated, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Add-ons Updated from {0} to {1}")
        ],
        "reviews_created" : [
            // L10n: {0} is an integer.
            gettext("Reviews Written, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Reviews Written from {0} to {1}")
        ],
        "users_created" : [
            // L10n: {0} is an integer.
            gettext("User Signups, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("User Signups from {0} to {1}")
        ],
        "collections_created" : [
            // L10n: {0} is an integer.
            gettext("Collections Created, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Collections Created from {0} to {1}")
        ],
        "subscribers"  : [
            // L10n: {0} is an integer.
            gettext("Subscribers, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Subscribers from {0} to {1}")
        ],
        "ratings"  : [
            // L10n: {0} is an integer.
            gettext("Ratings, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Ratings from {0} to {1}")
        ],
        "sales"  : [
            // L10n: {0} is an integer.
            gettext("Sales, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Sales from {0} to {1}")
        ],
        "installs"  : [
            // L10n: {0} is an integer.
            gettext("Installs, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Installs from {0} to {1}")
        ]
    },
    aggregateLabel: {
        "downloads" : [
            // L10n: {0} and {1} are integers.
            gettext("<b>{0}</b> in last {1} days"),
            // L10n: {0} is an integer and {1} and {2} are dates in YYYY-MM-DD format.
            gettext("<b>{0}</b> from {1} to {2}"),
        ],
        "usage"     : [
            // L10n: {0} and {1} are integers.
            gettext("<b>{0}</b> average in last {1} days"),
            // L10n: {0} is an integer and {1} and {2} are dates in YYYY-MM-DD format.
            gettext("<b>{0}</b> from {1} to {2}"),
        ]
    }
};
