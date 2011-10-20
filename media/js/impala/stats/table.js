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
                currentPage = undefined;

            $(document).ready(init);
            function init() {
                gotoPage(0);
                $paginator.delegate('.next', 'click', _pd(function() {
                    if ($(this).hasClass('disabled')) return;
                    gotoPage(currentPage+1);
                }));
                $paginator.delegate('.prev', 'click', _pd(function() {
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
                    view = {
                        metric  : metric,
                        group   : 'day',
                        range   : {
                            end     : z.date.ago('1 day', pageSize * page),
                            start   : z.date.ago('1 day', pageSize * page + pageSize)
                        }
                    };
                $.when(z.StatsManager.getDataRange(view))
                 .then(function(data) {
                     var fields     = z.StatsManager.getAvailableFields(view),
                         newBody    = '<tbody>',
                         newPage    = {},
                         newHead    = '<tr><th>' + gettext('Date') + '</th>',
                         start      = view.range.start,
                         end        = view.range.end,
                         step       = z.date.millis('1 day'),
                         row;

                     _.each(fields, function(f) {
                         newHead += '<th>';
                         var id = f.split('|').pop();
                         newHead += z.StatsManager.getPrettyName(metric, id);
                         newHead += '</th>';
                     });

                     for (var i=end; i>start; i-=step) {
                         row = data[i];
                         newBody += '<tr>';
                         newBody += '<th>' + Highcharts.dateFormat('%a, %b %e, %Y', new Date(i)) + "</th>";
                         if (!row) row = {};
                         _.each(fields, function(f) {
                             newBody += '<td>';
                             newBody += Highcharts.numberFormat(z.StatsManager.getField(row, f),0);
                             newBody += '</td>';
                         })
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