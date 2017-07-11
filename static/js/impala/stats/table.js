(function($) {
    "use strict";

    $.fn.csvTable = function(cfg) {
        $(this).each(function() {
            var $self       = $(this),
                $table      = $self.find('table'),
                $thead      = $self.find('thead'),
                $paginator  = $self.find('.paginator'),
                pageSize    = 14,
                pages       = {},
                metric      = $('.primary').attr('data-report'),
                currentPage;

            $(document).ready(init);
            function init() {
                gotoPage(0);
                $paginator.on('click', '.next', _pd(function() {
                    if ($(this).hasClass('disabled')) return;
                    gotoPage(currentPage+1);
                }));
                $paginator.on('click', '.prev', _pd(function() {
                    if ($(this).hasClass('disabled')) return;
                    gotoPage(currentPage-1);
                }));
            }

            function gotoPage(page) {
                if (page < 0) {
                    page = 0;
                }
                $paginator.find('.prev').toggleClass('disabled', page==0);
                if (pages[page]) {
                    showPage(page);
                } else {
                    $self.parent().addClass('loading');
                    $.when(getPage(page))
                     .then(function() {
                         showPage(page);
                         $self.parent().removeClass('loading');
                         getPage(page+1);
                         getPage(page-1);
                     });
                }
            }

            function showPage(page) {
                var p = pages[page];
                if (p) {
                    $table.find('tbody').hide();
                    p.el.show();
                    $thead.empty().html(p.head);
                }
                currentPage = page;
            }

            function getPage(page) {
                if (pages[page] || page < 0) return;
                var $def = $.Deferred(),
                    range = {
                        end     : Date.ago(pageSize * page + 'days'),
                        start   : Date.ago(pageSize * page + pageSize + 'days')
                    },
                    view = {
                        metric  : metric,
                        group   : 'day',
                        range   : range
                    };
                $.when(z.StatsManager.getDataRange(view))
                 .then(function(data) {
                     var fields     = z.StatsManager.getAvailableFields(view),
                         newBody    = '<tbody>',
                         newPage    = {},
                         newHead    = '<tr><th>' + gettext('Date') + '</th>',
                         row;

                     _.each(fields, function(f) {
                         var id = f.split('|').pop(),
                             prettyName = _.escape(z.StatsManager.getPrettyName(metric, id)),
                             trimmedPrettyName = (prettyName.length > 32) ? (prettyName.substr(0, 32) + '...') : prettyName;
                         newHead += format('<th title="{0}">', prettyName);
                         newHead += trimmedPrettyName;
                         newHead += '</th>';
                     });

                     var d = range.end.clone().backward('1 day'),
                         lastRowDate = range.start.clone().backward('1 day');
                     for (; lastRowDate.isBefore(d); d.backward('1 day')) {
                         row = data[d.iso()] || {};
                         newBody += '<tr>';
                         newBody += '<th>' + Highcharts.dateFormat('%a, %b %e, %Y', Date.iso(d)) + "</th>";
                         _.each(fields, function(f) {
                             newBody += '<td>';
                             if (metric == 'contributions' && f != 'count') {
                                 newBody += '$' + Highcharts.numberFormat(z.StatsManager.getField(row, f), 2);
                             } else {
                                 newBody += Highcharts.numberFormat(z.StatsManager.getField(row, f),0);
                             }
                             newBody += '</td>';
                         });
                        newBody += '</tr>';
                     }
                     newBody += '</tbody>';

                     newPage.el = $(newBody);
                     newPage.head = newHead;

                     $table.append(newPage.el);
                     pages[page] = newPage;

                     $def.resolve();
                 });
                 return $def;
            }
        });
    };
})(jQuery);
