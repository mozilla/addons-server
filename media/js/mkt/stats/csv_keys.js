var csv_keys = {
    installs: {
        'count': gettext('Installs')
    },
    usage: {
        'count': gettext('Daily Users')
    },
    revenue: {
        'count': gettext('Amount Earned')
    },
    sales: {
        'count': gettext('Units Sold')
    },
    refunds: {
        'count': gettext('Units Refunded')
    },
    currency_revenue: {
        'count': gettext('Amount Earned')
    },
    currency_sales: {
        'count': gettext('Units Sold')
    },
    currency_refunds: {
        'count': gettext('Units Refunded')
    },
    source_revenue: {
        'count': gettext('Amount Earned')
    },
    source_sales: {
        'count': gettext('Units Sold')
    },
    source_refunds: {
        'count': gettext('Units Refunded')
    },
    apps_count_new: {
        'count': gettext('Apps Added')
    },
    apps_count_installed: {
        'count': gettext('Apps Installed')
    },
    apps_review_count_new: {
        'count': gettext('Reviews')
    },
    mmo_user_count_new: {
        'count': gettext('New Users')
    },
    mmo_user_count_total: {
        'count': gettext('Total Users')
    },
    mmo_total_visitors: {
        'count': gettext('Total Visitors')
    },
    sources: {
        'null'                  : gettext('Unknown'),
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
        // Duplicate of line 75.
        //'cb-dl-featured'        : gettext('Category Landing Featured Carousel'),
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
        'count': gettext('Number of Contributions'),
        'total': gettext('Total Amount Contributed'),
        'average': gettext('Average Contribution')
    },
    overview: {
        'downloads' : gettext('Downloads'),
        'updates'   : gettext('Daily Users')
    },
    app_overview: {
        'installs': gettext('Installs'),
        'usage': gettext('Usage'),
        'sales': gettext('Units Sold')
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
        'installs' : [
            // L10n: {0} is an integer.
            gettext('Installs, last {0} days'),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext('Installs from {0} to {1}')
        ],
        'usage'  : [
            gettext('Daily Users, last {0} days'),
            gettext('Daily Users from {0} to {1}')
        ],
        'sales' : [
            gettext('Units Sold, last {0} days'),
            gettext('Units Sold from {0} to {1}')
        ],
        'revenue' : [
            gettext('Amount Earned, last {0} days'),
            gettext('Amount Earned {0} to {1}')
        ],
        'refunds' : [
            gettext('Units Refunded, last {0} days'),
            gettext('Units Refunded from {0} to {1}')
        ],
        'currency_sales' : [
            gettext('Total Units Sold by Currency'),
            gettext('Total Units Sold by Currency')
        ],
        'currency_revenue' : [
            gettext('Total Amount Earned by Currency'),
            gettext('Total Amount Earned by Currency')
        ],
        'currency_refunds' : [
            gettext('Total Units Refunded by Currency'),
            gettext('Total Units Refunded by Currency')
        ],
        'source_sales' : [
            gettext('Total Units Sold by Source'),
            gettext('Total Units Sold by Source')
        ],
        'source_revenue' : [
            gettext('Total Amount Earned by Source'),
            gettext('Total Amount Earned by Source')
        ],
        'source_refunds' : [
            gettext('Total Units Refunded by Source'),
            gettext('Total Units Refunded by Source')
        ],
        'apps_count_new': [
            gettext('Apps added'),
            gettext('Apps added')
        ],
        'apps_count_installed': [
            gettext('Apps installed'),
            gettext('Apps installed')
        ],
        'apps_review_count_new': [
            gettext('Reviews'),
            gettext('Reviews')
        ],
        'mmo_user_count_total': [
            gettext('Total users'),
            gettext('Total users')
        ],
        'mmo_user_count_new': [
            gettext('New users'),
            gettext('New users')
        ],
        'mmo_total_visitors': [
            gettext('Total visitors'),
            gettext('Total visitors')
        ]
    },
    aggregateLabel: {
        'downloads' : [
            // L10n: {0} and {1} are integers.
            gettext('<b>{0}</b> in last {1} days'),
            // L10n: {0} is an integer and {1} and {2} are dates in YYYY-MM-DD format.
            gettext('<b>{0}</b> from {1} to {2}')
        ],
        'usage'     : [
            // L10n: {0} and {1} are integers.
            gettext('<b>{0}</b> average in last {1} days'),
            // L10n: {0} is an integer and {1} and {2} are dates in YYYY-MM-DD format.
            gettext('<b>{0}</b> from {1} to {2}')
        ]
    }
};
