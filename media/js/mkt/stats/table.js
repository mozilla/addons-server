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
                nonDateMetrics = z.StatsManager.nonDateMetrics,
                currentPage;

            $(document).ready(function() {
                // My apps and multi-line charts won't get a table for now.
                if (metric != 'my_apps') {
                    init();
                    $('.tabular.csv-table footer').show();
                } else {
                    $('.tabular.csv-table footer').hide();
                }
            });

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
                $paginator.find('.prev').toggleClass('disabled', page === 0);
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
                // nonDateMetrics don't need pages (yet).
                if (metric in nonDateMetrics) {
                    $paginator.find('.next').toggleClass('disabled');
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
                     var fields = z.StatsManager.getAvailableFields(view),
                         currencyMetrics = z.StatsManager.currencyMetrics,
                         newBody = '<tbody>',
                         newHead = gettext('Date'),
                         newPage = {},
                         row;

                     // Handle headers other than 'Date'.
                     switch(nonDateMetrics[metric]) {
                         case 'currency':
                             newHead = gettext('Currency');
                             break;
                         case 'source':
                             newHead = gettext('Source');
                             break;
                     }
                     newHead = '<tr><th>' + newHead + '</th>';

                     _.each(fields, function(f) {
                         var id = f.split('|').pop(),
                             prettyName = z.StatsManager.getPrettyName(metric, id);
                         newHead += format('<th title="{0}">', prettyName);
                         newHead += prettyName;
                         newHead += '</th>';
                     });

                     // Manually create a table for nonDateMetrics with
                     // breakdown field on left and data on right.
                     if (metric in nonDateMetrics) {
                        _.each(data, function(datum) {
                            newBody += '<tr>';
                            newBody += '<th>' + gettext(datum[nonDateMetrics[metric]]) + '</th>';

                            // Insert data (supports multiple fields).
                            _.each(fields, function(f) {
                                newBody += '<td>';
                                if (metric in currencyMetrics) {
                                    newBody += '$' + Highcharts.numberFormat(z.StatsManager.getField(datum, f), 2);
                                } else {
                                    newBody += Highcharts.numberFormat(z.StatsManager.getField(datum, f), 0);
                                }
                                newBody += '</td>';
                            });
                            newBody += '</tr>';
                        });
                     }
                     // Manually create a table for date-related metrics with
                     // date on left and data on right.
                     else {
                         var d = range.end.clone().backward('1 day'),
                             lastRowDate = range.start.clone().backward('1 day');
                         for (; lastRowDate.isBefore(d); d.backward('1 day')) {
                             row = data[d.iso()] || {};
                             newBody += '<tr>';
                             newBody += '<th>' + Highcharts.dateFormat('%a, %b %e, %Y', Date.iso(d)) + "</th>";

                            // Insert data (supports multiple fields).
                             _.each(fields, function(f) {
                                 newBody += '<td>';
                                 if (metric in currencyMetrics) {
                                     newBody += '$' + Highcharts.numberFormat(z.StatsManager.getField(row, f), 2);
                                 } else {
                                     newBody += Highcharts.numberFormat(z.StatsManager.getField(row, f), 0);
                                 }
                                 newBody += '</td>';
                             });
                            newBody += '</tr>';
                         }
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
