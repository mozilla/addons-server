require(['prefetchManifest']);


(function() {

    // Delete user button.
    $('#delete-user button').click(function() {
        $('#delete-user .modal-delete').show().find('textarea').focus();
    });
    $('.modal .close').click(_pd(function() {
        $(this).closest('.modal-delete').hide();
    }));

    // Search suggestions.
    $('#account-search').searchSuggestions($('#account-search-suggestions'),
                                           processResults);
    $('#app-search').searchSuggestions($('#app-search-suggestions'),
                                       processResults);

    // Show All Results.
    var searchTerm = '';
    z.doc.on('mousedown', '.lookup-search-form .show-all', function() {
        // Temporarily disable clearCurrentSuggestions in suggestions.js,
        // which usually runs on blur. But here we don't want this click to
        // clear the suggestions list.
        $('input[type=search]').off('blur');
    }).on('click', '.lookup-search-form .show-all', function() {
        var $form = $(this).closest('.lookup-search-form');
        // Make request for all data.
        processResults({
            data: {
                all_results: true,
                q: searchTerm
            },
            searchTerm: searchTerm,
            $results: $('.search-suggestions', $form)
        }).then(function() {
            // After loading the suggestion list, retattach blur handler.
            var handler = require('suggestions')($('.search-suggestions', $form)).delayDismissHandler;
            $('input[type=search]', $form).focus().on('blur', handler);
        });
    });

    var searchLimit = parseInt($('form.lookup-search-form').data('search-limit'), 10);
    var maxResults = parseInt($('form.lookup-search-form').data('max-results'), 10);
    function processResults(settings) {
        if (!(settings && settings.constructor === Object)) {
            return;
        }
        var def = $.Deferred();

        var first_item = template(
            '<li><a class="sel" href="{url}"><span>{id}</span> ' +
            '<em class="name">{name}</em> ' +
            '<em class="email">{email}</em></a></li>'
        );
        var li_item = template(
            '<li><a href="{url}"><span>{id}</span> ' +
            '<em class="name">{name}</em> ' +
            '<em class="email">{email}</em></a></li>'
        );
        var showAllLink =
            '<li><a class="show-all no-blur">' + gettext('Show All Results') +
            '</a></li>';
        var maxSearchResultsMsg =
            '<li class="max">' + format(gettext('Over {0} results found, consider refining your search.'), maxResults) + '</li>'

        $.ajaxCache({
            url: settings.$results.attr('data-src'),
            data: settings.data || settings.$form.serialize(),
            newItems: function(formdata, items) {
                var eventName;
                if (items !== undefined) {
                    var ul = '';
                    items = items.results;
                    $.each(items, function(i, item) {
                        var d = {
                            url: escape_(item.url) || '#',
                            id: item.id,
                            email: item.email || '',
                            name: item.name
                        };
                        if (d.name) {
                            d.name = escape_(d.name);
                            // Append the item only if it has a name.
                            if (i === 0) {
                                ul += first_item(d);
                            } else {
                                ul += li_item(d);
                            }
                        }
                    });
                    if (items.length == searchLimit) {
                        // Allow option to show all results if not already
                        // showing all results, and we know there are more results.
                        ul += showAllLink;
                    } else if (items.length == maxResults) {
                        // Show a message if max search results hit (~200).
                        ul += maxSearchResultsMsg;
                    }
                    settings.$results.html(ul);
                    searchTerm = settings.searchTerm;
                }
                settings.$results.trigger('highlight', [settings.searchTerm])
                                 .trigger('resultsUpdated', [items]);
                def.resolve();
            }
        });

        return def;
    }
})();
