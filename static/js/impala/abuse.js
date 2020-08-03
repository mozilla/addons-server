$(function () {
  var $abuse = $('fieldset.abuse');
  if ($abuse.find('legend a').length) {
    var $ol = $abuse.find('ol');
    $ol.hide();
    $abuse.find('legend a, .cancel').click(
      _pd(function () {
        $ol.slideToggle('fast');
      }),
    );
  }
});
