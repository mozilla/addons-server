var csv_keys = {
    installs: {
        'count': gettext('Installs')
    },
    usage: {
        "count": gettext('Daily Users')
    },
    sales: {
        'count': gettext('Sales')
    },
    revenue: {
        'count': gettext('Revenue')
    },
    refunds: {
        'count': gettext('Refunds')
    },
    currency_revenue: {
        'count': gettext('Revenue')
    },
    currency_sales: {
        'count': gettext('Sales')
    },
    currency_refunds: {
        'count': gettext('Refunds')
    },
    source_revenue: {
        'count': gettext('Revenue')
    },
    source_sales: {
        'count': gettext('Sales')
    },
    source_refunds: {
        'count': gettext('Refunds')
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
        'sales': gettext('Sales')
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
        "installs" : [
            // L10n: {0} is an integer.
            gettext("Installs, last {0} days"),
            // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
            gettext("Installs from {0} to {1}")
        ],
        "usage"  : [
            gettext("Daily Users, last {0} days"),
            gettext("Daily Users from {0} to {1}")
        ],
        "sales" : [
            gettext("Sales, last {0} days"),
            gettext("Sales from {0} to {1}")
        ],
        "revenue" : [
            gettext("Revenue, last {0} days"),
            gettext("Revenue {0} to {1}")
        ],
        "refunds" : [
            gettext("Refunds, last {0} days"),
            gettext("Refunds from {0} to {1}")
        ],
        "currency_sales" : [
            gettext("Total Sales by Currency"),
            gettext("Total Sales by Currency")
        ],
        "currency_revenue" : [
            gettext("Total Revenue by Currency"),
            gettext("Total Revenue by Currency")
        ],
        "currency_refunds" : [
            gettext("Total Refunds by Currency"),
            gettext("Total Refunds by Currency")
        ],
        "source_sales" : [
            gettext("Total Sales by Source"),
            gettext("Total Sales by Source")
        ],
        "source_revenue" : [
            gettext("Total Revenue by Source"),
            gettext("Total Revenue by Source")
        ],
        "source_refunds" : [
            gettext("Total Refunds by Source"),
            gettext("Total Refunds by Source")
        ]
    },
    aggregateLabel: {
        "downloads" : [
            // L10n: {0} and {1} are integers.
            gettext("<b>{0}</b> in last {1} days"),
            // L10n: {0} is an integer and {1} and {2} are dates in YYYY-MM-DD format.
            gettext("<b>{0}</b> from {1} to {2}")
        ],
        "usage"     : [
            // L10n: {0} and {1} are integers.
            gettext("<b>{0}</b> average in last {1} days"),
            // L10n: {0} is an integer and {1} and {2} are dates in YYYY-MM-DD format.
            gettext("<b>{0}</b> from {1} to {2}")
        ]
    }
};
