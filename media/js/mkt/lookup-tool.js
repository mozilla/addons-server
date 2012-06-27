(function() {
    $('#account-search').searchSuggestions($('#account-search-suggestions'),
                                           processResults);
    $('#app-search').searchSuggestions($('#app-search-suggestions'),
                                       processResults);

    function processResults(settings) {
        if (!(settings && settings.constructor === Object)) {
            return;
        }

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

        $.ajaxCache({
            url: settings['$results'].attr('data-src'),
            data: settings['$form'].serialize(),
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
                    settings['$results'].html(ul);
                }
                settings['$results'].trigger('highlight', [settings.searchTerm])
                                    .trigger('resultsUpdated', [items]);
            }
        });
    }
})();
