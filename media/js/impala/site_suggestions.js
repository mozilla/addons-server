// Init site search suggestions and populate the suggestions container.
(function() {
    // AMO search init.
    $('#search #search-q').searchSuggestions($('#site-search-suggestions'),
                                             processResults, 'AMO');

    function processResults(settings) {
        if (!settings || !settings.category) {
            return;
        }

        // Update the 'Search add-ons for <b>"{addon}"</b>' text.
        settings['$results'].find('p b').html(format('"{0}"',
                                                     settings.searchTerm));

        var li_item = template(
            '<li><a href="{url}"><span {cls} {icon}>{name}</span>{subtitle}</a></li>'
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
                            url: escape_(item.url) || '#',
                            icon: '',
                            cls: '',
                            subtitle: ''
                        };
                        if (item.icon) {
                            d.icon = format(
                                'style="background-image:url({0})"',
                                escape_(item.icon)
                            );
                        }
                        if (item.cls) {
                            d.cls = format('class="{0}"',
                                           escape_(item.cls));
                            if (item.cls == 'cat') {
                                d.subtitle = format(
                                    ' <em class="subtitle">{0}</em>',
                                    gettext('Category')
                                );
                            }
                        }
                        if (item.name) {
                            d.name = escape_(item.name);
                            // Append the item only if it has a name.
                            ul += li_item(d);
                        }
                    });
                    settings['$results'].find('ul').html(ul);
                }
                settings['$results'].trigger('highlight', [settings.searchTerm])
                                    .trigger('resultsUpdated', [items]);
            }
        });
    }
})();
