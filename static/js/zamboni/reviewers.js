(function() {
    if($('.daily-message').length) {
        initDailyMessage();
    }

    var show_comments = function(e) {
        e.preventDefault();
        var $me = $(e.target);
        $me.hide();
        $me.next().show();
        $me.parents('tr').next().show();
    };

    var hide_comments = function(e) {
        e.preventDefault();
        var $me = $(e.target);
        $me.hide();
        $me.prev().show();
        $me.parents('tr').next().hide();
    };


    $('a.show').click(show_comments);
    $('a.hide').click(hide_comments);

    if ($('.queue-search').length) {
        initQueueSearch($('.queue-search'));
    }

    if($('#review-actions').length > 0) {
        initReviewActions();
    }

    if ($('#extra-review-actions').length) {
        initExtraReviewActions();
    }

    if ($('.all-backgrounds').length) {
        initBackgroundImagesForTheme();
    }

    if($('#monthly.highcharts-container').length) {
        initPerformanceStats();
    }

    if($('#scroll_sidebar').length && !$('body.mobile, body.tablet').length &&
       !z.capabilities.mobile) {
        initScrollingSidebar();
    }

    if($('#addon-queue').length) {
        initQueue();
    }

    // Show add-on ID when icon is clicked
    if ($("#addon[data-id], #persona[data-id]").length) {
      $("#addon .icon").click(function() {
        window.location.hash = "id=" + $("#addon, #persona").attr("data-id");
      });
    }
})();


function initReviewActions() {
    var groups = $('#id_canned_response').find('optgroup');

    function showForm(element, pageload) {
        var $element = $(element),
            value = $element.find('input').val(),
            $data_toggle = $('form.review-form').find('.data-toggle');

        pageload = pageload || false;
        $element.closest('.review-actions').addClass('on');
        $('.review-actions .action_nav ul li').removeClass('on-tab');
        $element.find('input').prop('checked', true);

        $element.addClass('on-tab');

        if (pageload) {
          $('#review-actions-form').show();
        } else {
          $('#review-actions-form').slideDown();
          $('#review-actions').find('.errorlist').remove();
        }

        // Hide everything, then show the ones containing the value we're
        // interested in. An extra | (the separator used) is added at the end
        // to make sure we don't match things with a common prefix (i.e. don't
        // show elements with data-value="reject_multiple_versions" when the
        // value is "reject".)
        $data_toggle.hide();
        $data_toggle.filter('[data-value*="' + value + '|"]').show();

        /* Fade out canned responses */
        var label = $element.text().trim();
        groups.css('color', '#AAA');
        groups.filter("[label='"+label+"']").css('color', '#444');
    }

    $('#review-actions .action_nav ul li:not(.disabled)').click(function() {
        showForm(this);
    });

    /* Canned Response stuff */
    $('.review-actions-canned select').change(function() {
        insertAtCursor($('#id_comments'), $(this).val());
    });

    var review_checked = $('#review-actions [name=action]:checked');
    if(review_checked.length > 0) {
      showForm(review_checked.closest('li'), true);
    }

    /* Install Triggers */

    $('.files .install').click(_pd(function(){
        var $this = $(this),
            installer = $this.is('[data-type="search-tools"]') ? z.installSearch : z.installAddon;
        installer($this.text(), $this.attr('href'), "");
    }));


    /* Who's currently on this page? */
    var addon_id = $('#addon').attr('data-id');
    var url = $('#addon').attr('data-url');
    function check_currently_viewing() {
        $.post(url, {'addon_id': addon_id}, function(d){
            var show = d.is_user != 1 && typeof d.current_name != "undefined",
                       $current = $('.currently_viewing_warning');

            $current.toggle(show);

            if(show) {
              var title;
              if (d.is_user == 2) {
                /* 2 is when the editor has reached the lock limit */
                title = d.current_name;
              } else {
                title = format(gettext('{name} was viewing this page first.'),
                                       {name: d.current_name});
              }
              $current_div = $current.filter('div');
              $current_div.find('strong').remove();
              $current_div.prepend($('<strong>', {'text': title}));
            }

            setTimeout(check_currently_viewing, d.interval_seconds * 1000);
        });
    }
    if (!(z.capabilities.localStorage && window.localStorage.dont_poll)) {
        check_currently_viewing();
    }

    /* Item History */
    $('.review-files tr.listing-header').click(function() {
        $(this).next('tr.listing-body').toggle();
    });

    var storage = z.Storage(),
        eh_setting = storage.get('reviewers_history'),
        eh_els = $('#history .review-files tr.listing-body'),
        eh_size = eh_els.length;
    if(!eh_setting) eh_setting = 3;

    toggleHistory();

    function toggleHistory() {
        eh_els.slice(eh_size - eh_setting, eh_setting).show();
        eh_els.slice(0, eh_size - eh_setting).hide();
    }

    $('.eh_open').click(_pd(function() {
        eh_setting = $(this).attr('data-num');
        storage.set('reviewers_history', eh_setting);
        toggleHistory();
        highlightHistory();
    }));

    function highlightHistory() {
        $('#history a').removeClass('on');
        $(format('#history a[data-num="{0}"]', eh_setting)).addClass('on');
    }
    highlightHistory();
}

function callReviewersAPI(apiUrl, method, data, successCallback) {
    var apiToken = $('form.more-actions').data('api-token');
    if (data) {
        data = JSON.stringify(data);
    }
    $.ajax({
        url: apiUrl,
        data: data,
        type: method,
        beforeSend: function (xhr) {
            xhr.setRequestHeader ("Authorization", 'Bearer ' + apiToken);
        },
        processData: false,
        contentType: 'application/json',
        success: successCallback,
     });
}

function initExtraReviewActions() {
    /* Inline actions that should trigger a XHR and modify the form element
     * accordingly.
     */
    // Checkbox-style actions. Only for subscribe/unsubscribe.
    $('#notify_new_listed_versions').click(_pd(function() {
        var $input = $(this).prop('disabled', true);  // Prevent double-send.
        var checked = !$input.prop('checked');  // It's already changed.
        var apiUrl;
        if (checked) {
            apiUrl = $input.data('api-url-unsubscribe');
        } else {
            apiUrl = $input.data('api-url-subscribe');
        }
        callReviewersAPI(apiUrl, 'post', null, function() {
            $input.prop('disabled', false);
            $input.prop('checked', !checked);
        });
    }));

    // One-off-style buttons.
    $('#clear_admin_code_review, #clear_admin_content_review, #clear_pending_info_request, #clear_auto_approval_delayed_until').click(_pd(function() {
        var $button = $(this).prop('disabled', true);  // Prevent double-send.
        var apiUrl = $button.data('api-url');
        var data = $button.data('api-data') || null;
        var method = $button.data('api-method') || 'post';
        callReviewersAPI(apiUrl, method, data, function() {
            $button.remove();
        });
    }));

    // Toggle-style buttons.
    $([
        '#force_disable_addon',
        '#force_enable_addon',
        '#disable_auto_approval',
        '#enable_auto_approval',
        '#allow_resubmission',
        '#deny_resubmission'
    ].join(',')).click(_pd(function() {
        var $button = $(this).prop('disabled', true);  // Prevent double-send.
        var $other_button = $($button.data('toggle-button-selector'));
        var apiUrl = $button.data('api-url');
        var data = $button.data('api-data') || null;
        var method = $button.data('api-method') || 'post';
        callReviewersAPI(apiUrl, method, data, function() {
            $button.prop('disabled', false).parents('li').addClass('hidden').hide();
            $other_button.parents('li').removeClass('hidden').show();
         });
    }));
}

function initBackgroundImagesForTheme() {

    function rollOverInit(e) {
        if (!e.target.complete) return;
        var $target = $(e.target);
        $target.attr('height', e.target.naturalHeight);
        $target.attr('width', e.target.naturalWidth);
        $target.parent().zoomBox();
    }

    function loadBackgroundImages($parent_element) {
        var url = $parent_element.data('backgrounds-url');
        if (!url) return;
        var xhr = new XMLHttpRequest();
        xhr.open("GET", url);
        xhr.responseType = "json";
        // load the image as a blob so we can treat it as a File
        xhr.onload = function() {
            var jsonResponse = xhr.response,
                loop_len = Object.keys(jsonResponse).length;
                loop_count = 0;
            $.each(jsonResponse,
                function(background_filename, background_b64) {
                    loop_count++;
                    var blob = b64toBlob(background_b64),
                        imageUrl = window.URL.createObjectURL(blob);
                    var $div_element = $("<div>")
                                       .addClass("background zoombox")
                                       .appendTo($parent_element);
                    var $img_element = $("<img>")
                                       .attr("src", imageUrl)
                                       .attr("width", "1000")
                                       .attr("height", "200")
                                       .appendTo($div_element);
                    var span_content = document.createTextNode(
                        format("Background file {0} of {1} - {2}",
                               [loop_count, loop_len, background_filename]));
                    $("<span>").append(span_content).appendTo($div_element);
                    $img_element.on('load', rollOverInit).trigger('load');
                });
        };
        xhr.send();
    }

    loadBackgroundImages($('div.all-backgrounds'));
}

function insertAtCursor(textarea, text) {
    var area = $(textarea)[0],
        scrollPos = area.scrollTop;
    // IE
    if (document.selection) {
        area.focus();
        var rng = document.selection.createRange();
        rng.text = text + rng.text;
    // FF/Safari/Chrome
    } else if (area.selectionStart || area.selectionStart == '0') {
        area.focus();
        var startPos = area.selectionStart;
        area.value = area.value.substring(0, startPos) + text + area.value.substring(startPos, area.value.length);
        area.setSelectionRange(startPos + text.length, startPos + text.length);
        // everything else - append text to end
    } else {
        area.value += text;
    }
    // restore scrollbar location
    area.scrollTop = scrollPos;
}


function initDailyMessage(doc) {
    var $motd = $('.daily-message', doc),
        storage = z.Storage();
    if ($('#editor-motd', doc).length) {
        // The message on the MOTD page should never be closable, so don't
        // show close button nor attach handlers.
        return;
    }
    $motd.find('.close').show();
    if (storage.get('motd_closed') != $('p', $motd).text()) {
        // You haven't read this spam yet? Here, I have something to show you.
        $motd.show();
    }
    $motd.find('.close').click(function(e) {
        e.stopPropagation();
        storage.set('motd_closed', $('.daily-message p').text());
        $motd.slideUp();
    });
}


function initQueue() {
    var $q = $('#addon-queue[data-url]');
    if (!$q.length) {
        return;
    }

    var url = $q.attr('data-url');
    var addon_ids = $.map($('.addon-row'), function(el) {
            return $(el).attr('data-addon');
        });
    if(!(('localStorage' in window) && window.localStorage.dont_poll)) {
        (function checkCurrentlyViewing() {
            $.get(url, {'addon_ids': addon_ids.join(',')}, function(data) {
                $('#addon-queue .locked').removeClass('locked')
                                         .prop('title', '');
                $.each(data, function(k, v) {
                    $('#addon-' + k).addClass('locked')
                                    .attr('title',
                                          format(gettext('{name} was viewing this add-on first.'),
                                                 {name: v}));
                });
                setTimeout(checkCurrentlyViewing, 2000);
            });
        })();
    }

    var pop = $('#popup-notes').hide(),
        loadNotes = function(e) {
            var addon_id = $(e.click_target).closest('tr').attr('data-addon');
            pop.html(gettext('Loading&hellip;'));
            $.get(pop.attr('data-version-url') + addon_id, function(data) {
                pop.html('');
                var empty = true;
                if(data.release_notes) {
                    pop.append($('<strong>', {'text': gettext('Version Notes')}));
                    pop.append($('<div>', {'class': 'version-notes', 'text': data.release_notes}));
                    empty = false;
                }
                if(data.approval_notes) {
                    pop.append($('<strong>', {'text': gettext('Notes for Reviewers')}));
                    pop.append($('<div>', {'class': 'version-notes', 'text': data.approval_notes}));
                    empty = false;
                }
                if(empty) {
                    pop.append($('<em>', {'text': gettext('No version notes found')}));
                }
            });
            return true;
        },
        loadReview = function(e) {
            var addon_id = $(e.click_target).closest('tr').attr('data-review-log');
            pop.html(gettext('Loading&hellip;'));
            $.get(pop.attr('data-review-url') + addon_id, function(data) {
                pop.html('');
                var empty = true;
                if(data.reviewtext) {
                    pop.append($('<strong>', {'text': gettext('Review Text')}));
                    pop.append($('<div>', {'class': 'version-notes', 'text': data.reviewtext}));
                    empty = false;
                }
                if(empty) {
                    pop.append($('<em>', {'text': gettext('Review notes found')}));
                }
            });
            return true;
        };

    $('.addon-version-notes a').each(function(i, el) {
        $(pop).popup(el, { pointTo: el, callback: loadNotes, width: 500});
    });

    $('.addon-review-text a').each(function(i, el) {
        $(pop).popup(el, { pointTo: el, callback: loadReview, width: 500});
    });

}

function initQueueSearch(doc) {
    $('.toggle-queue-search').click(_pd(function() {
        $('.advanced-search').slideToggle();
    }));

    $('#id_application_id', doc).change(function(e) {
        var maxVer = $('#id_max_version', doc),
            sel = $(e.target),
            appId = $('option:selected', sel).val();

        if (!appId) {
            $('option', maxVer).remove();
            maxVer.append(format('<option value="{0}">{1}</option>',
                                 ['', gettext('Select an application first')]));
            return;
        }
        $.post(sel.attr('data-url'), {'application_id': appId}, function(d) {
            $('option', maxVer).remove();
            $.each(d.choices, function(i, ch) {
                maxVer.append(format('<option value="{0}">{1}</option>',
                                     [ch[0], ch[1]]));
            });
        });
    });
}


function initScrollingSidebar() {
    var $window = $(window),
        $sb = $('#scroll_sidebar'),
        addon_top = $('#addon').offset().top,
        current_state = false;

    function setSticky(state) {
        if (state == current_state) return;
        current_state = state;
        $sb.toggleClass('sticky', state);
    }

    $window.scroll(_.throttle(function() {
        setSticky(window.scrollY > addon_top);
    }, 20));
}


function initPerformanceStats() {
    var container = $('#monthly'),
        groups = {'usercount': $('#reviews_user').text(),
                  'teamavg': gettext('Average Reviews')};

    /* View Other User Stats */
    $('#select_user').change(function(){
        var $this = $(this),
            user = $this.val();

        if(user !== "") {
            window.location.href = $this.attr('data-url') + user;
        }
    });


    /* Create Charts */

    createChart(container, groups, JSON.parse(container.attr('data-chart')));

    function createChart(container, groups, data) {
        var labels = [],
            data_points = {},
            chart_series = [];


        $.each(groups, function(key, name){
            data_points[key] = {'name': name, 'data':[]};
        });

        $.each(data, function(k, vals) {
            labels.push(vals.label);
            $.each(vals, function(group, amount){
                if(groups[group]){
                    data_points[group].data.push(parseFloat(amount));
                }
            });
        });

        $.each(data_points, function(k, vals){
            chart_series.push(vals);
        });

        new Highcharts.Chart({
                chart: {
                    renderTo: container[0],
                    defaultSeriesType: 'line',
                    marginRight: 130,
                    marginBottom: 25
                },
                title: {
                   text: ' ',
                    x: 0 //center
                },
                xAxis: {
                   categories: labels
                },
                yAxis: {
                    title: { text: gettext('Number of Reviews') },
                    plotLines: [{value: 0, width: 1, color: '#808080'}],
                    min: 0
                },
                tooltip: {
                    formatter: function() {
                        return '<b>'+ this.series.name +'</b><br/>' + this.x +': '+ this.y;
                    }
                },
                legend: {
                    layout: 'vertical',
                    align: 'right',
                    verticalAlign: 'top',
                    x: -10,
                    y: 100,
                    borderWidth: 0
                },
                series: chart_series,
                credits: {
                  enabled: false
                }
            });
    }

}
