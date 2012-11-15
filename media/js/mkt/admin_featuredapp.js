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
            var $this = $(elm);
            var $app = $this.closest('.featured-app');
            var $siblingDate = $this.siblings('input[type=date]');
            var url = $app.data('url');
            var appid = $app.data('app-id');
            var isStartDate = $siblingDate.hasClass('date-range-start');
            $this.datepicker({
                dateFormat: 'yy-mm-dd',
                onSelect: function(dateText) {
                    if (isStartDate) {
                        saveFeaturedDate(url, appid, dateText, $siblingDate.val());
                    } else {
                        saveFeaturedDate(url, appid, $siblingDate.val(), dateText);
                    }
                }
            });
            $this.change(function(e) {
                if (isStartDate) {
                    saveFeaturedDate($app.data('url'), $app.data('app-id'),
                                     $this.val(), $siblingDate.val());
                } else {
                    saveFeaturedDate($app.data('url'), $app.data('app-id'),
                                     $siblingDate.val(), $this.val());
                }
            });
        });
    }

    function saveFeaturedDate(url, appid, start, end) {
        var data = {};
        data.startdate = start;
        data.enddate = end;
        data.app = appid;
        $.ajax({'type': 'POST', 'url': url, 'data': data});
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
            'category': cat.val()
        });
    }

    function updateAppsList(cat, newItem) {
        return appslistXHR('POST', {
            'category': cat.val(),
            'add': newItem
        });
    }

    function deleteFromAppsList(cat, oldItem) {
        return appslistXHR('POST', {
            'category': cat.val(),
            'delete': oldItem
        });
    }

    function appslistXHR(verb, data) {
        var appslist = $featured;
        var q = $.ajax({'type': verb, 'url': appslist.data('src'), 'data': data});
        q.then(function(data) {
            appslist.html(data);
        });
        return q;
    }

    var region_carrier_update = _pd(function(e) {
        var $choices = $(e.target);
        var $appParent = $choices.closest('ul');
        function carrierName(v) {
            var x = v.split('.');
            if (x[0] == 'carrier') {
                return x[1];
            } else {
                return null;
            }
        }

        var regions = $choices.children('option').filter(function(i, opt) {
            return opt.selected && !carrierName(opt.value);
        }).map(function(i, sopt) {return sopt.value;});

        var carriers = $choices.children('option').map(function(i, opt) {
            if (opt.selected) {
                return carrierName(opt.value);
            }
        });

        $.ajax({
            'type': 'POST',
            'url': $appParent.data('url'),
            'data': {
                'region': $.makeArray(regions),
                'carrier': $.makeArray(carriers),
                'app': $appParent.data('app-id')
            }
        });
    });


    $featured.delegate('.remove', 'click', _pd(function() {
        deleteFromAppsList($('#categories'), $(this).data('id'));
    })).delegate('select.localepicker', 'change', region_carrier_update)
       .delegate('select.carrierpicker', 'change', region_carrier_update);

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
