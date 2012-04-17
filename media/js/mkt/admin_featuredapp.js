function registerAddonAutocomplete(node) {
    var $td = node.closest('td');
    node.autocomplete({
    minLength: 3,
    width: 300,
    source: function(request, response) {
      $.getJSON($(node).attr('data-src'), {
          q: request.term
      }, response);
    },
    focus: function(event, ui) {
      $(node).val(ui.item.name);
      return false;
    },
    select: function(event, ui) {
        $(node).val(ui.item.name).attr('data-id', ui.item.id);
        var current = template(
            '<a href="{url}" target="_blank" ' +
                'class="collectionitem"><img src="{icon}">{name}</a>');
            $td.find('.current-webapp').show().html(current({
                url: ui.item.url,
                icon: ui.item.icon,
                name: ui.item.name
            }));
        $td.find('input[type=hidden]').val(ui.item.id);
        node.val('');
        node.hide();
        return false;
        }
    }).data('autocomplete')._renderItem = function(ul, item) {
        var html = format('<a>{0}<b>ID: {1}</b></a>', [item.name, item.id]);
            return $('<li>').data('item.autocomplete', item).append(html).appendTo(ul);
        };
}

function newAddonSlot(id) {
    var $tbody = $("#" + id + "-webapps")
    var $form = $tbody.next().children("tr").clone();
    var $input = $form.find('input.placeholder');
    registerAddonAutocomplete($input);
    $form.find('input[type=hidden]').attr(
        "name", $tbody.children().length + "-" + id +"-webapp");
    $tbody.append($form);
}

$(document).ready(function(){
    $("#home-webapps, #featured-webapps").delegate(
        '.remove', 'click', _pd(function() {$(this).closest('tr').remove();}));

    $('#home-add').click(_pd(function() { newAddonSlot("home"); }));
    $('#featured-add').click(_pd(function() { newAddonSlot("featured"); }));
});