/* This abstracts the uploading of all files.  Currently, it's only
 * extended by addonUploader().  Eventually imageUploader() should as well */

(function($) {
    var instance_id = 0,
    boundary = "BoUnDaRyStRiNg";

    function getErrors(results) {
        return results.errors;
    }

    var settings = {'filetypes': [], 'getErrors': getErrors, 'cancel': $()};

    $.fn.fileUploader = function( options ) {

        return $(this).each(function(){
            var $upload_field = $(this),
                formData = false,
                $form = $upload_field.closest('form'),
                errors = false,
                aborted = false;

            if (options) {
                $.extend( settings, options );
            }

            $upload_field.bind({"change": uploaderStart});

            $(settings['cancel']).click(_pd(function(){
                $upload_field.trigger('upload_action_abort');
            }));

            function uploaderStart(e) {
                if($upload_field[0].files.length == 0) {
                    return;
                }

                var domfile = $upload_field[0].files[0],
                    url = $upload_field.attr('data-upload-url'),
                    csrf = $("input[name=csrfmiddlewaretoken]").val(),
                    file = {'name': domfile.name || domfile.fileName,
                            'size': domfile.size,
                            'type': domfile.type};

                formData = new z.FormData();
                aborted = false;

                $upload_field.trigger("upload_start", [file]);

                /* Disable uploading while something is uploading */
                $upload_field.attr('disabled', true);
                $upload_field.parent().find('a').addClass("disabled");
                $upload_field.bind("reenable_uploader", function(e) {
                    $upload_field.attr('disabled', false);
                    $upload_field.parent().find('a').removeClass("disabled");
                });

                var exts = new RegExp("\\\.("+settings['filetypes'].join('|')+")$", "i");

                if(!file.name.match(exts)) {
                    errors = [gettext("The filetype you uploaded isn't recognized.")];

                    $upload_field.trigger("upload_errors", [file, errors]);
                    $upload_field.trigger("upload_finished", [file]);

                    return;
                }

                // We should be good to go!
                formData.open("POST", url, true);
                formData.append("csrfmiddlewaretoken", csrf);
                if(options.appendFormData) {
                    options.appendFormData(formData);
                }

                if(domfile instanceof File) { // Needed b/c of tests.
                  formData.append("upload", domfile);
                }

                $upload_field.unbind("upload_action_abort").bind("upload_action_abort", function() {
                    aborted = true;
                    formData.xhr.abort();
                    errors = [gettext("You cancelled the upload.")];
                    $upload_field.trigger("upload_errors", [file, errors]);
                    $upload_field.trigger("upload_finished", [file]);
                });

                formData.xhr.upload.addEventListener("progress", function(e) {
                    if (e.lengthComputable) {
                        var pct = Math.round((e.loaded * 100) / e.total);
                        $upload_field.trigger("upload_progress", [file, pct]);
                    }
                }, false);

                formData.xhr.onreadystatechange = function(e){
                    $upload_field.trigger("upload_onreadystatechange",
                                          [file, formData.xhr, aborted]);
                };

                formData.send();
            }
        });

    }
})(jQuery);
