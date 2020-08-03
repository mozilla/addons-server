function clearErrors(context) {
  $('.errorlist', context).remove();
  $('.error', context).removeClass('error');
}

function populateErrors(context, o) {
  clearErrors(context);
  var $list = $('<ul class="errorlist"></ul>');
  $.each(o, function (i, v) {
    var $row = $('[name=' + i + ']', context).closest('.row');
    $row.addClass('error');
    $row.append($list.append($(format('<li>{0}</li>', _.escape(v)))));
  });
}

function fieldFocused(e) {
  var tags = /input|keygen|meter|option|output|progress|select|textarea/i;
  return tags.test(e.target.nodeName);
}

function postUnsaved(data) {
  $('input[name="unsaved_data"]').val(JSON.stringify(data));
}

function loadUnsaved() {
  return JSON.parse($('input[name="unsaved_data"]').val() || '{}');
}
