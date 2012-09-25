// Init site search suggestions and populate the suggestions container.
(function() {
    // MKT search init.
    $('#search #search-q').searchSuggestions($('#site-search-suggestions'),
                                             processResults, 'MKT');

    function processResults(settings) {
        if (!settings) {
            return;
        }

        var li_item = template(
            '<li><a href="{url}"><span>{name}</span></a></li>'
        );

        $.ajaxCache({
            url: settings['$results'].attr('data-src'),
            data: settings['$form'].serialize() + '&cat=' + settings.category,
            newItems: function(formdata, items) {
                var eventName;
                if (items !== undefined) {
                    var ul = '';
                    $.each(items, function(i, item) {
                        var d = {
                            url: escape_(item.url) || '#'
                        };
                        if (item.name) {
                            d.name = escape_(item.name);
                            // Append the item only if it has a name.
                            ul += li_item(d);
                        }
                    });
                    settings['$results'].find('ul').html(ul);
                }
                settings['$results'].addClass('visible')
                                    .trigger('resultsUpdated', [items]);
                $('#site-header').addClass('suggestions');
            }
        });
    }
})();
