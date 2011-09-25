function clearErrors(context) {
    $('.errorlist', context).remove();
    $('.error', context).removeClass('error');
}


function populateErrors(context, o) {
    clearErrors(context);
    var $list = $('<ul class="errorlist"></ul>');
    $.each(o, function(i, v) {
        var $row = $('[name=' + i + ']', context).closest('.row');
        $row.addClass('error');
        $row.append($list.append($(format('<li>{0}</li>', v))));
    });
}
