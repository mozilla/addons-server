$(document).ready(function() {

    //Ownership
    if ($("#author_list").length) {
        initAuthorFields();
    }

    //Payments
    if ($('.payments').length) {
        initPayments();
    }

    // Edit Versions
    if($('#upload-file').length) {
        initEditVersions();
    }

    // View versions
    if($('#version-list').length) {
        initVersions();
    }
});


$(document).ready(function() {
    $.ajaxSetup({cache: false});

    $('.more-actions-popup').popup('.more-actions', {
        width: 'inherit',
        offset: {x: 15},
        callback: function(obj) {
            return {pointTo: $(obj.click_target)};
        }
    });

    truncateFields();

    initCompatibility();

    $('#edit-addon').delegate('h3 a', 'click', function(e){
        e.preventDefault();

        parent_div = $(this).closest('.edit-addon-section');
        a = $(this);

        (function(parent_div, a){
            parent_div.load($(a).attr('href'), addonFormSubmit);
        })(parent_div, a);

        return false;
    });

    $('.addon-edit-cancel').live('click', function(){
        parent_div = $(this).closest('.edit-addon-section');
        parent_div.load($(this).attr('href'));
        return false;
    });
});


function truncateFields() {
    var els = [
            "#addon_description",
            "#developer_comments"
        ];
    $(els.join(', ')).each(function(i,el) {
        var $el = $(el),
            originalHTML = $el.html();
        $el.delegate("a.truncate_expand", "click", function(e) {
            e.preventDefault();
            $el.html(originalHTML).css('max-height','none');
        })
        .vtruncate({
            truncText: format("&hellip; <a href='#' class='truncate_expand'>{0}</a>",[gettext("More")])
        });
    });
}


function addonFormSubmit() {
    parent_div = $(this);

    (function(parent_div){
        $('form', parent_div).submit(function(){
        $.post($(parent_div).find('form').attr('action'),
                $(this).serialize(), function(d){
                    $(parent_div).html(d).each(addonFormSubmit);
                    truncateFields();
                });
            return false;
        });
    })(parent_div);
}


$("#user-form-template .email-autocomplete")
    .attr("placeholder", gettext("Enter a new author's email address"));


function initVersions() {
    $('#modals').hide();

    $('#modal-delete-version').modal('.version-delete .remove',
        { width: 400,
          callback:function(d){
                $('.version_id', this).val($(d.click_target).attr('data-version'));
                return true;
            }
          });

    $('#modal-cancel').modal('#cancel-review',
        { width: 400
          });


    $('#modal-delete').modal('#delete-addon',
        { width: 400,
          });


    $('#modal-disable').modal('#disable-addon',
        { width: 400,
          });


}

function initEditVersions() {
    // Hide the modal
    $('.upload-status').hide();

    // Modal box
    $modal = $(".add-file-modal").modal(".add-file", {
        width: '450px',
        hideme: false,
        callback:resetModal
    });

    // Reset link
    $('.upload-file-reset').click(function(e) {
        e.preventDefault();
        resetModal();
    });

    // Cancel link
    $('.upload-file-cancel').click(function(e) {
        e.preventDefault();
        $modal.hideMe();
    });

    // Upload form submit
    $('#upload-file').submit(function(e){
        e.preventDefault();

        $('.upload-status-button-add, .upload-status-button-close').hide();

        fileUpload($('#upload-file-input'), $(this).attr('action'));

        $('.upload-file-box').hide();
        $('.upload-status').show();
    });

    function fileUpload(img, url) {

        var file = img[0].files[0],
            fileName = file.name,
            fileSize = file.size,
            fileData = '';

        var boundary = "BoUnDaRyStRiNg";

        text = format(gettext('Preparing {0}'), [fileName]);
        $('#upload-status-text').text(text);
        $('#upload-status-bar').addClass('progress-idle');

        // Wrap in a setTimeout so it doesn't freeze the browser before
        // the status above can be set.

        setTimeout(function(){
            fileData = file.getAsBinary();

            var xhr = new XMLHttpRequest();
            xhr.upload.addEventListener("progress", function(e) {
                if (e.lengthComputable) {
                    var pct = Math.round((e.loaded * 100) / e.total) + "%";
                    $('#upload-status-bar div').animate({'width': pct}, 500);
                }
            }, false);

            xhr.open("POST", url, true);

            xhr.onreadystatechange = function(){ onupload(xhr, fileName) };

            xhr.setRequestHeader("Content-Type", "multipart/form-data;" +
                                                 "boundary="+boundary);
            xhr.setRequestHeader("Content-Length", fileSize);
            xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');

            var token = $("#upload-file input[name=csrfmiddlewaretoken]").val();

            // Things like spacing and quotes need to be exactly as follows, so
            // edit with care.

            var body  = 'Content-Type: multipart/form-data; ';
                body += format('boundary={0}\r\n', [boundary]);
                body += format('Content-Length: {0}\r\n', [fileSize]);

                body += format("--{0}\r\n", [boundary]);

                body += 'Content-Disposition: form-data; '
                body += 'name="csrfmiddlewaretoken"\r\n\r\n';
                body += format('{0}\r\n', [token]);

                body += format("--{0}\r\n", [boundary]);

                body += 'Content-Disposition: form-data; name="upload"; ';
                body += format('filename="{0}"\r\n', [fileName]);
                body += 'Content-Type: application/octet-stream\r\n\r\n';

                body += fileData + '\r\n';
                body += format('--{0}--', [boundary]);

                text = format(gettext('Uploading {0}'), [fileName]);
                $('#upload-status-text').text(text);
                $('#upload-status-bar').removeClass('progress-idle');

                xhr.sendAsBinary(body);
        }, 10);

        return true;
    }
}

function onupload(xhr, fileName) {
    if (xhr.readyState == 4 && xhr.responseText &&
            (xhr.status == 200 || xhr.status == 304)) {

        $('#upload-status-bar div').animate({'width': '100%'}, 500, function() {
            text = format(gettext('Validating {0}'), [fileName]);
            $('#upload-status-text').text(text);

            $(this).parent().addClass('progress-idle');

            json = JSON.parse(xhr.responseText);
            addonUploaded(json, fileName);
        });
    }
}

function addonUploaded(json, fileName) {
    v = json.validation;

    if(!v) {
        setTimeout(function(){
            $.getJSON( $('#upload-file').attr('action') + "/" + json.upload,
                function(d){ addonUploaded(d, fileName); })
        }, 1000);
    } else {
        $('#upload-status-bar').removeClass('progress-idle')
                               .addClass(v.errors ? 'bar-fail' : 'bar-success');
        $('#upload-status-bar div').fadeOut();

        text = format(gettext('Validated {0}'), [fileName]);
        $('#upload-status-text').text(text);

        // TODO(gkoberger): Use templates here, rather than +'s

        body  = "<strong>";
        if(!v.errors) {
            body += format(ngettext(
                    "Your add-on passed validation with no errors and {0} warning.",
                    "Your add-on passed validation with no errors and {0} warnings.",
                    v.warnings), [v.warnings]);
        } else {
            body += format(ngettext(
                    "Your add-on failed validation with {0} error.",
                    "Your add-on failed validation with {0} errors.",
                    v.errors), [v.errors]);
        }
        body += "</strong>";

        body += "<ul>";
        if(v.errors) {
            $.each(v.messages, function(k, t) {
                if(t.type == "error") {
                    body += "<li>" + t.message + "</li>";
                }
            });
        }
        body += "</ul>";

        // TODO(gkoberger): Add a link when it becomes available

        body += "<a href='#'>";
        body += gettext('See full validation report');
        body += '</a>';

        statusclass = v.errors ? 'status-fail' : 'status-pass';
        $('#upload-status-results').html(body).addClass(statusclass);

        $('.upload-status-button-add').hide();
        $('.upload-status-button-close').show();

        inputDiv = $('.upload-status-button-close');

        if(v.errors) {
            text_reset = gettext('Try Again');
            text_cancel = gettext('Cancel');
        } else {
            text_reset = gettext('Upload Another');
            text_cancel = gettext('Finish Uploading');
        }

        $('.upload-file-reset', inputDiv).text(text_reset);
        $('.upload-file-cancel', inputDiv).text(text_cancel);
    }
}

function initPayments() {
    var previews = [
        "img/zamboni/contributions/passive.png",
        "img/zamboni/contributions/after.png",
        "img/zamboni/contributions/roadblock.png",
    ],
        media_url = $("body").attr("data-media-url"),
        to = false,
        img = $("<img id='contribution-preview'/>");
        moz = $("input[value=moz]");
    img.hide().appendTo($("body"));
    moz.parent().after(
        $("<a class='extra' target='_blank' href='http://www.mozilla.org/foundation/donate.html'>"+gettext('Learn more')+"</a>"));
    $(".nag li label").each(function (i,v) {
        var pl = new Image();
        pl.src = media_url + previews[i];
        $(this).after(format(" &nbsp;<a class='extra' href='{0}{1}'>{2}</a>", [media_url, previews[i], gettext('Example')]));
    });
    $(".nag").delegate("a.extra", "mouseover", function(e) {
        var tgt = $(this);
        img.attr("src", tgt.attr("href")).css({
            position: 'absolute',
            'pointer-events': 'none',
            top: tgt.offset().top-350,
            left: ($(document).width()-755)/2
        });
        clearTimeout(to);
        to = setTimeout(function() {
            img.fadeIn(100);
        }, 300);
    }).delegate("a.extra", "mouseout", function(e) {
        clearTimeout(to);
        img.fadeOut(100);
    })
    .delegate("a.extra", "click", function(e) {
        e.preventDefault();
    });
    $("#do-setup").click(function (e) {
        e.preventDefault();
        $("#setup").removeClass("hidden").show();
        $(".intro").hide();
    });
    $("#setup-cancel").click(function (e) {
        e.preventDefault();
        $(".intro").show();
        $("#setup").hide();
    });
    $(".recipient").change(function (e) {
        var v = $(this).val();
        $(".paypal").hide(200);
        $(format("#org-{0}", [v])).removeClass("hidden").show(200);
    });
    $("#id_enable_thankyou").change(function (e) {
        if ($(this).attr("checked")) {
            $(".thankyou-note").show().removeClass("hidden");
        } else {
            $(".thankyou-note").hide();
        }
    }).change();
}


function initAuthorFields() {
    var request = false,
        timeout = false,
        manager = $("#id_form-TOTAL_FORMS"),
        empty_form = template($("#user-form-template").html().replace(/__prefix__/g, "{0}")),
        author_list = $("#author_list");
    author_list.sortable({
        items: ".author",
        handle: ".handle",
        containment: author_list,
        tolerance: "pointer",
        update: renumberAuthors
    });
    addAuthorRow();

    $("#id_has_eula").change(function (e) {
        if ($(this).attr("checked")) {
            $(".eula").show().removeClass("hidden");
        } else {
            $(".eula").hide();
        }
    });
    $("#id_has_priv").change(function (e) {
        if ($(this).attr("checked")) {
            $(".priv").show().removeClass("hidden");
        } else {
            $(".priv").hide();
        }
    });
    var other_val = $(".license-other").attr("data-val");
    $(".license").click(function (e) {
        if ($(this).val() == other_val) {
            $(".license-other").show().removeClass("hidden");
        } else {
            $(".license-other").hide();
        }
    });

    $(".author .errorlist").each(function() {
        $(this).parent()
            .find(".email-autocomplete")
            .addClass("tooltip")
            .addClass("invalid")
            .addClass("formerror")
            .attr("title", $(this).text());
    });

    $("#author_list").delegate(".email-autocomplete", "keypress", validateUser)
    .delegate(".email-autocomplete", "keyup", validateUser)
    .delegate(".remove", "click", function (e) {
        e.preventDefault();
        var tgt = $(this),
            row = tgt.parents("li");
        if (author_list.children(".author:visible").length > 1) {
            if (row.hasClass("initial")) {
                row.find(".delete input").attr("checked", "checked");
                row.hide();
            } else {
                row.remove();
                manager.val(author_list.children(".author").length);
                renumberAuthors();
            }
        }
    });
    function renumberAuthors() {
        author_list.children(".author").each(function(i, el) {
            $(this).find(".position input").val(i);
        });
    }
    function addAuthorRow() {
        var numForms = author_list.children(".author").length;
        author_list.append(empty_form([numForms]))
                   .sortable("refresh");
        author_list.find(".blank .email-autocomplete")
                   .placeholder();
        manager.val(author_list.children(".author").length);
        renumberAuthors();
    }
    function validateUser(e) {
        var tgt = $(this),
            row = tgt.parents("li");
        if (row.hasClass("blank")) {
            tgt.removeClass("placeholder")
               .attr("placeholder", undefined);
            row.removeClass("blank")
               .addClass("author");
            addAuthorRow();
        }
        if (tgt.val().length > 2) {
            if (timeout) clearTimeout(timeout);
            timeout = setTimeout(function () {
                tgt.addClass("ui-autocomplete-loading")
                   .removeClass("invalid")
                   .removeClass("valid");
                request = $.ajax({
                    url: tgt.attr("data-src"),
                    data: {q: tgt.val()},
                    success: function(data) {
                        tgt.removeClass("ui-autocomplete-loading")
                           .addClass("valid");
                    },
                    error: function() {
                        tgt.removeClass("ui-autocomplete-loading")
                           .addClass("invalid");
                    }
                });
            }, 500);
        }
    }
}


function resetModal(obj) {

    upload = $("<input type='file'>").attr('name', 'upload')
                                     .attr('id', 'upload-file-input');

    $('.upload-file-box').show();
    $('.upload-status').hide();

    $('.upload-status-button-add').show();
    $('.upload-status-button-close').hide();

    $('#upload-status-bar').attr('class', '');
    $('#upload-status-text').text("");
    $('#upload-file-input').replaceWith(upload); // Clear file input
    $('#upload-status-results').text("").attr("class", "");
    $('#upload-status-bar div').css('width', 0).show();
    $('#upload-status-bar').removeClass('progress-idle');

    return true;
}


function initCompatibility() {
    $('p.add-app a').live('click', function(e) {
        e.preventDefault();
        var outer = $(this).closest('form');

        $('tr.app-extra', outer).each(function() {
            addAppRow(this);
        });

        $('.new-apps', outer).toggle();

        $('.new-apps ul').delegate('a', 'click', function(e) {
            e.preventDefault();
            var extraAppRow = $('tr.app-extra td[class=' + $(this).attr('class') + ']', outer);
            extraAppRow.parents('tr').find('input:checkbox').removeAttr('checked')
                       .closest('tr').removeClass('app-extra');

            $(this).closest('li').remove();

            if (!$('tr.app-extra', outer).length)
                $('p.add-app', outer).hide();
        });
    });

    $('.compat-versions .remove').live('click', function(e) {
        e.preventDefault();
        var appRow = $(this).closest('tr');

        appRow.addClass('app-extra');

        if (!appRow.hasClass('app-extra-orig'))
            appRow.find('input:checkbox').attr('checked', true);

        $('p.add-app:hidden', $(this).closest('form')).show();
        addAppRow(appRow);
    });

    $('.compat-update-modal').modal('a.compat-update', {
        delegate: $('.item-actions li.compat, .compat-error-popup'),
        hideme: false,
        emptyme: true,
        callback: compatModalCallback
    });

    $('.compat-error-popup').popup('.compat-error', {
        width: '450px',
        callback: function(obj) {
            var $popup = this;
            $popup.delegate('.close, .compat-update', 'click', function(e) {
                e.preventDefault();
                $popup.hideMe();
            });
            return {pointTo: $(obj.click_target)};
        }
    });
}


function addAppRow(obj) {
    var outer = $(obj).closest('form'),
        appClass = $('td.app', obj).attr('class');
    if (!$('.new-apps ul', outer).length)
        $('.new-apps', outer).html('<ul></ul>');
    if ($('.new-apps ul a[class=' + appClass + ']', outer).length)
        return;
    var appLabel = $('td.app', obj).text(),
        appHTML = '<li><a href="#" class="' + appClass + '">' + appLabel + '</a></li>';
    $('.new-apps ul', outer).append(appHTML);
}


function compatModalCallback(obj) {
    var $widget = this,
        ct = $(obj.click_target),
        form_url = ct.attr('data-updateurl');

    if ($widget.hasClass('ajax-loading'))
        return;
    $widget.addClass('ajax-loading');

    $widget.load(form_url, function(e) {
        $widget.removeClass('ajax-loading');
    });

    $('form.compat-versions').live('submit', function(e) {
        e.preventDefault();
        $widget.empty();

        if ($widget.hasClass('ajax-loading'))
            return;
        $widget.addClass('ajax-loading');

        var widgetForm = $(this);
        $.post(widgetForm.attr('action'), widgetForm.serialize(), function(data) {
            $widget.removeClass('ajax-loading');
            if ($(data).find('.errorlist').length) {
                $widget.html(data);
            } else {
                var c = $('.item[data-addonid=' + widgetForm.attr('data-addonid') + '] .item-actions li.compat');
                c.load(c.attr('data-src'));
                $widget.hideMe();
            }
        });
    });

    return {pointTo: ct};
}
