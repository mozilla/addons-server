(function() {
    var $featured = $('#featured-webapps');

    function registerAddonAutocomplete(node) {
        var $node = $(node);

        $node.autocomplete({
            'minLength': 3,
            'width': 300,
            'source': function(request, response) {
                $.getJSON($node.attr('data-src'), {
                    'q': request.term,
                    'category': $('#categories').val()
                }, response);
            },
            'focus': function(event, ui) {
                $node.val(ui.item.name);
                return false;
            },
            'select': function(event, ui) {
                updateAppsList($('#categories'), ui.item.id).then(function() {
                    registerDatepickers();
                });
                return false;
            }
        }).data('autocomplete')._renderItem = function(ul, item) {
            var html = format('<a href="#">{0}<b>ID: {1}</b></a>', [item.name, item.id]);
            return $('<li>').data('item.autocomplete', item).append(html)
                                                            .appendTo(ul);
        };
    }

    function registerDatepickers() {
        $('#featured-webapps input[type=date]').each(function(i, elm) {
            $(elm).datepicker({
                dateFormat: 'yy-mm-dd'
            });
        });
    }

    function newAddonSlot(id) {
        var $container = $featured;
        var $next = $container.next();
        var $form = $next.children().clone();

        // This seems to be the best way to send the input for autocompletion.
        registerAddonAutocomplete($form[1]);
        $container.append($form);
    }

    function showAppsList(cat) {
        return appslistXHR('GET', {
            category: cat.val()
        }).then(function(data) {
            $featured.html(data);
        });
    }

    function carrierName(v) {
        var x = v.split('.');
        if (x[0] == 'carrier') {
            return x[1];
        } else {
            return null;
        }
    }
    function collectForm(f) {
        var $choices = $('select.localepicker option', f);
        var regions = $choices.filter(function(i, opt) {
                return opt.selected && !carrierName(opt.value);
            }).map(function(i, sopt) {return sopt.value;}).get();
        var carriers = $choices.map(function(i, opt) {
                if (opt.selected) {
                    return carrierName(opt.value);
                }
            }).get();
        return {
            id: $('.featured-app', f).data('app-id'),
            startdate: $('input.date-range-start', f).val(),
            enddate: $('input.date-range-end', f).val(),
            regions: regions,
            carriers: carriers
        };
    }
    function collectUnsaved(newItem) {
        var $unsaved = $('input[name="unsaved"]').parent();
        var extras = $unsaved.map(function() {return collectForm(this);}).get();
        if (newItem) {
            extras.push({id: newItem, startdate: null, enddate: null,
                         regions: [], carriers: []});
        };
        return extras;
    };

    function updateAppsList(cat, newItem) {
        var extras = collectUnsaved(newItem);
        return appslistXHR('GET', {
            category: cat.val(),
            extras: JSON.stringify(extras)
        }).then(function(data) {
            $featured.html(data);
        });
    };

    function deleteFromAppsList(cat, oldItem) {
        return appslistXHR('POST', {
            'category': cat.val(),
            'delete': oldItem
        });
    };

    function appslistXHR(verb, data) {
        return $.ajax({type: verb, url: $featured.data('src'), data: data});
    };

    $featured.delegate('input, select', 'keyup change', _pd(function () {
        $('button[name="saveit"]', $(this).parents('.app-container')).attr('disabled', false);
    }));

    $featured.delegate('button[name="saveit"]', 'click', _pd(function() {
        var $button = $(this);
        var $parent = $button.parents('.app-container');
        $parent.children('input[name="unsaved"]').remove();
        appslistXHR('POST', {
                        category: $('#categories').val(),
                        extras: JSON.stringify(collectUnsaved()),
                        save: JSON.stringify(collectForm($parent))
                    }).then(function() {$button.attr('disabled', true);});
    }));
    $featured.delegate('.remove', 'click', _pd(function() {
        var $parent = $(this).parents('.app-container');
        deleteFromAppsList($('#categories'), $(this).data('id')).then(
            function() { $parent.remove();});
    }));

    var categories = $('#categories');
    var p = $.ajax({'type': 'GET', 'url': categories.data('src')});

    p.then(function(data) {
        categories.html(data);
        showAppsList(categories).then(function() {
            registerDatepickers();
        });
    });

    categories.change(function(e) {
        showAppsList(categories).then(function() {
            registerDatepickers();
        });
    });

    $('#featured-add').click(_pd(function() {newAddonSlot();}));

})();
