/* To use this, upload_field must have a parent form that contains a
   csrf token. Additionally, the field must have the attribute
   data-upload-url.  It will upload the files (note: multiple files
   are supported; they are uploaded separately and each event is triggered
   separately), and clear the upload field.

   The data-upload-url must return a JSON object containing an `upload_hash`
   and an `errors` array.  If the error array is empty ([]), the upload is
   assumed to be a success.

   Example:
    No Error: {"upload_hash": "123ABC", "errors": []}
    Error: {"upload_hash": "", "errors": ["Uh oh!"]}

   In the events, the `file` var is a JSON object with the following:
    - name
    - size
    - type: image/jpeg, etc
    - instance: A unique ID for distinguishing between multiple uploads.
    - dataURL: a data url for the image (`false` if it doesn't exist)

   Events:
    - upload_start(e, file): The upload is started
    - upload_success(e, file, upload_hash): The upload was successful
    - upload_errors(e, file, array_of_errors): The upload failed
    - upload_finished(e, file): Called after a success OR failure
    - [todo] upload_progress(e, file, percent): Percentage progress of the file
      upload.

    - upload_start_all(e): All uploads are starting
    - upload_finished_all(e): All uploads have either succeeded or failed

    [Note: the upload_*_all events are only triggered if there is at least one
    file in the upload box when the "onchange" event is fired.]
 */

// Get an object URL across browsers.
$.fn.objectUrl = function (offset) {
  var files = $(this)[0].files,
    url = false;
  if (z.capabilities.fileAPI && files.length) {
    offset = offset || 0;
    var f = files[offset];
    if (typeof window.URL !== 'undefined') {
      url = window.URL.createObjectURL(f);
    } else if (typeof window.webkitURL == 'function') {
      url = window.webkitURL.createObjectURL(f);
    } else if (typeof f.getAsDataURL == 'function') {
      url = f.getAsDataURL();
    }
  }
  return url;
};

(function ($) {
  var instance_id = 0;

  $.fn.imageUploader = function () {
    var $upload_field = this,
      outstanding_uploads = 0,
      files = $upload_field[0].files,
      url = $upload_field.attr('data-upload-url'),
      csrf = $upload_field.closest('form').find('input[name^=csrf]').val();

    // No files? No API support? No shirt? No service.
    if (!z.capabilities.fileAPI || files.length === 0) {
      return false;
    }

    $upload_field.trigger('upload_start_all');

    // Loop through the files.
    $.each(files, function (v, f) {
      var data = '',
        file = {
          instance: instance_id,
          name: f.name || f.fileName,
          size: f.size,
          type: f.type,
          aborted: false,
          dataURL: false,
        },
        finished = function () {
          outstanding_uploads--;
          if (outstanding_uploads <= 0) {
            $upload_field.trigger('upload_finished_all');
          }
          $upload_field.trigger('upload_finished', [file]);
        },
        formData = new z.FormData();

      instance_id++;
      outstanding_uploads++;

      if (
        $upload_field.attr('data-allowed-types').split('|').indexOf(file.type) <
        0
      ) {
        var errors = [gettext('Images must be either PNG or JPG.')];
        if (typeof $upload_field.attr('multiple') !== 'undefined') {
          // If we have a `multiple` attribute, assume not an icon.
          if ($upload_field.attr('data-allowed-types').indexOf('video') > -1) {
            errors.push([gettext('Videos must be in WebM.')]);
          }
        }
        $upload_field.trigger('upload_start', [file]);
        $upload_field.trigger('upload_errors', [file, errors]);
        finished();
        return;
      }

      file.dataURL = $upload_field.objectUrl(v);

      // And we're off!
      $upload_field.trigger('upload_start', [file]);

      // Set things up
      formData.open('POST', url, true);
      formData.append('csrfmiddlewaretoken', csrf);
      formData.append('upload_image', f);

      // Monitor progress and report back.
      formData.xhr.onreadystatechange = function () {
        if (
          formData.xhr.readyState == 4 &&
          formData.xhr.responseText &&
          (formData.xhr.status == 200 || formData.xhr.status == 304)
        ) {
          var json = {};
          try {
            json = JSON.parse(formData.xhr.responseText);
          } catch (err) {
            var error = gettext('There was a problem contacting the server.');
            $upload_field.trigger('upload_errors', [file, error]);
            finished();
            return false;
          }

          if (json.errors.length) {
            $upload_field.trigger('upload_errors', [file, json.errors]);
          } else {
            $upload_field.trigger('upload_success', [file, json.upload_hash]);
          }
          finished();
        }
      };

      // Actually do the sending.
      formData.send();
    });

    // Clear out images, since we uploaded them.
    $upload_field.val('');
  };
})(jQuery);
