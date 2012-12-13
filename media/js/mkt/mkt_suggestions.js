// Init site search suggestions and populate the suggestions container.
(function() {
    // MKT search init.
    // Disable suggestions on Gaia for now.
    var suggestions;
    if (!z.capabilities.gaia || z.enableSearchSuggestions) {
        suggestions = $('#search #search-q').searchSuggestions(
            $('#site-search-suggestions'), processResults, 'MKT');

        suggestions.on('dismissed', abortRequest);
    }

    var current_search = null;
    var previous_request = null;

    function processResults(settings) {
        // Remember the previous search term so that only one of consecutive
        // duplicate queries makes the request to ajaxCache. This prevents the
        // duplicate requests from aborting themselves in the middle of
        // ajaxCache request.
        // Further reading: https://gist.github.com/4273860
        var search_term = settings['$form'].serialize().slice(2);
        if (!settings || current_search == search_term) {
            return;
        }

        var li_item = template(
            '<li><a href="{url}"><span>{name}</span></a></li>'
        );

        var new_request = $.ajaxCache({
            url: settings['$results'].attr('data-src'),
            data: settings['$form'].serialize() + '&cat=' + settings.category,
            newItems: function(formdata, items) {
                var eventName,
                    listitems = '';

                if (items !== undefined) {
                    $.each(items, function(i, item) {
                        var d = {
                            url: escape_(item.url) || '#'
                        };
                        if (item.name) {
                            d.name = escape_(item.name);
                            // Append the item only if it has a name.
                            listitems += li_item(d);
                        }
                    });
                }

                // Populate suggestions and make them visible.
                if (listitems) {
                    settings['$results'].find('ul').html(listitems);
                    settings['$results'].addClass('visible')
                                        .trigger('resultsUpdated', [items]);
                    $('#site-header').addClass('suggestions');
                }
            }
        });

        current_search = search_term;
        abortRequest();
        previous_request = new_request;
    }

    function abortRequest() {
        if (previous_request) {
            previous_request.abort();
            previous_request = null;
        }
    }

    // Clear search suggestions at start and end of fragmentload.
    z.page.on('startfragmentload fragmentloaded', function() {
        abortRequest();
        $('#site-search-suggestions').trigger('dismiss').find('ul').empty();
    });

})();
