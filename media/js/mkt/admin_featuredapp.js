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
                       ui.item.id);
        return false;
        }
    }).data('autocomplete')._renderItem = function(ul, item) {
        var html = format('<a>{0}<b>ID: {1}</b></a>', [item.name, item.id]);
        return $('<li>').data('item.autocomplete', item).append(html).appendTo(ul);
    };
}

function registerDatepicker(node) {
    var $startPicker = node.find('.start-date-picker');
    var $tabl = $startPicker.closest('table');
    var url = $tabl.data('url');
    var appid = $tabl.data('app-id');
    $startPicker.datepicker({
        dateFormat: 'yy-mm-dd',
        onSelect: function(dateText) {
            node.find('.date-range-start').val(dateText);
            saveFeaturedDate('startdate', url, appid, dateText);
        }
    });
    var $endPicker = node.find('.end-date-picker');
    $endPicker.datepicker({
        dateFormat: 'yy-mm-dd',
        onSelect: function(dateText) {
            node.find('.date-range-end').val(dateText);
            saveFeaturedDate('enddate', url, appid, dateText);
        }
    });

  var $start = node.find('.date-range-start');
    $start.change(
      function (e) {
        saveFeaturedDate('startdate', $tabl.data('url'), $tabl.data('app-id'), $start.val());
      });
  var $end = node.find('.date-range-end');
    $end.change(
      function (e) {
        saveFeaturedDate('enddate', $tabl.data('url'), $tabl.data('app-id'), $end.val());
      });

}

function saveFeaturedDate(which, url, appid, val) {
    var data = {};
    data[which] = val;
    data.app = appid;
    $.ajax({type: 'POST', url: url, data: data});
}

function newAddonSlot(id) {
    var $tbody = $("#featured-webapps");
    var $form = $tbody.next().children("tr").clone();
    var $input = $form.find('input.placeholder');
    registerAddonAutocomplete($input);
    registerDatepicker($form);
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
    var appslist = $("#featured-webapps");
    var p = $.ajax({type: 'GET',
                    url: categories.data("src")});
    p.then(function(data) {
        categories.html(data);
        showAppsList(categories).then(
            function () {
                registerDatepicker(appslist);
            });
    });
    categories.change(function (e) {
        showAppsList(categories).then(
            function () {
                registerDatepicker(appslist);
            });
    });
    $('#featured-add').click(_pd(function() { newAddonSlot(); }));
});
