/* Remove "Go" buttons from <form class="go" */
$(document).ready(function () {
  $('form.go')
    .change(function () {
      this.submit();
    })
    .find('button')
    .hide();
});
