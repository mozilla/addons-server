function registerAddonAutocomplete(node) {
    var $td = node.closest('td');
    node.autocomplete({
    minLength: 3,
    width: 300,
    source: function(request, response) {
      $.getJSON($(node).attr('data-src'), {
          q: request.term,
          category: $("#categories").val()
      }, response);
    },
    focus: function(event, ui) {
      $(node).val(ui.item.name);
      return false;
    },
    select: function(event, ui) {
        updateAppsList($("#categories"),
                       ui.item.id).then(
                           function(x) {
                               registerDatepickers($("#featured-webapps"));
                           });
        return false;
        }
    }).data('autocomplete')._renderItem = function(ul, item) {
        var html = format('<a>{0}<b>ID: {1}</b></a>', [item.name, item.id]);
        return $('<li>').data('item.autocomplete', item).append(html).appendTo(ul);
    };
}

function registerDatepickers() {
    $("#featured-webapps .featured-app").each(function (i, n) { registerDatepicker($(n));});
}

function registerDatepicker(node) {
    var $startPicker = node.find('.start-date-picker');
    var $tabl = $startPicker.closest('table').last();
    var url = $tabl.data('url');
    var appid = $tabl.data('app-id');
    var $start = node.find('.date-range-start');
    var $end = node.find('.date-range-end');
    $startPicker.datepicker({
        dateFormat: 'yy-mm-dd',
        onSelect: function(dateText) {
                $start.val(dateText);
            saveFeaturedDate(url, appid, dateText, $end.val());
        }
    });
    var $endPicker = node.find('.end-date-picker');
    $endPicker.datepicker({
        dateFormat: 'yy-mm-dd',
        onSelect: function(dateText) {
                $end.val(dateText);
            saveFeaturedDate(url, appid, $start.val(), dateText);
        }
    });

    $start.change(
      function (e) {
        saveFeaturedDate($tabl.data('url'), $tabl.data('app-id'), $start.val(), $end.val());
      });
    $end.change(
      function (e) {
        saveFeaturedDate($tabl.data('url'), $tabl.data('app-id'), $start.val(), $end.val());
      });

}

function saveFeaturedDate(url, appid, start, end) {
    var data = {};
    data["startdate"] = start;
    data["enddate"] = end;
    data.app = appid;
    $.ajax({type: 'POST', url: url, data: data});
}

function newAddonSlot(id) {
    var $tbody = $("#featured-webapps");
    var $form = $tbody.next().children("tr").clone();
    var $input = $form.find('input.placeholder');
    registerAddonAutocomplete($input);
    $tbody.append($form);
}

function showAppsList(cat) {
    return appslistXHR('GET', {
        category: cat.val()
    });
}

function updateAppsList(cat, newItem) {
    return appslistXHR('POST', {
        category: cat.val(),
        add: newItem
    });
}

function deleteFromAppsList(cat, oldItem) {
    return appslistXHR('POST', {
        category: cat.val(),
        delete: oldItem
    });
}

function appslistXHR(verb, data) {
    var appslist = $("#featured-webapps");
    var q = $.ajax({type: verb, url: appslist.data("src"), data: data});
    q.then(function (data) {
        appslist.html(data);
    });
    return q;
}

$(document).ready(function(){
    $("#featured-webapps").delegate(
        '.remove',
        'click',
        _pd(function() {
            deleteFromAppsList($("#categories"), $(this).data("id"));
        })
    );
    $('#featured-webapps').delegate(
        'select.localepicker',
        'change',
        _pd(function (e) {
            var $region = $(e.target);
            var $tabl = $region.closest('table');
            $.ajax({
                type: 'POST',
                url: $tabl.data('url'),
                data: {
                    'region':
                        _($region.children('option'))
                            .filter(function(opt) {return opt.selected})
                            .map(function(sopt) {return sopt.value}),
                    'app': $tabl.data('app-id')
                }
            });
        })
    );
    var categories = $("#categories");
    var p = $.ajax({type: 'GET',
                    url: categories.data("src")});
    p.then(function(data) {
        categories.html(data);
        showAppsList(categories).then(
            function () {
                registerDatepickers();
            });
    });
    categories.change(function (e) {
        showAppsList(categories).then(
            function () {
                registerDatepickers();
            });
    });
    $('#featured-add').click(_pd(function() { newAddonSlot(); }));
});
