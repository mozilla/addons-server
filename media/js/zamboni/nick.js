$(document).ready(function() {
    $('.sparklines').sparkline('html', {width: '8em', fillColor: false});
    $('#rec-stats').tablesorter();
    $('input[name=date]').datepicker({dateFormat: 'yy-mm-dd'})
    .change(function() {
        this.form.submit();
    });
});
