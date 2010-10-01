/**
 * PageTable: a simple paginated table- can be locally or remotely populated with data
 * Configuration: (All options required)
 *     el: the <table> element of the table
 *     columns: an array of column configuration objects
 *     report: the AMO report name
**/


function PageTable(_el) {
    this.tableEl = $(_el);
    this.paginator = {
        ol: $("<ol class='pagination'></ol>"),
        li: [],
        next_li: $("<li><a rel='next' href='#'>Next</a></li>"),
        prev_li: $("<li><a rel='prev' href='#'>Prev</a></li>"),
        num_buttons: 10,
        start: 1
    };
    this.pages = [];
    this.currentpage = 0;

    this.format = {
        date: function (value) {
            return Highcharts.dateFormat('%a, %b %e, %Y', new Date(value));
        },
        number: function (value) {
            return Highcharts.numberFormat(value, 0);
        }
    };

    var $th = $("thead th", this.tableEl);

    var columns = [];
    var barColumns = [];
    $th.each(function (i, v) {
        var $v = $(v),
            col = {};
        col.field = $v.getData("field");
        col.format = $v.getData("format");
        if ($v.getData("bar_column")) {
            barColumns.push({
                valueColumn: i+1,
                barColor: '#26a2ce',
                className: 'bar',
                width: $v.getData("bar_width")
            });
        }
        columns.push(col);
    })
    this.columns = columns;

    this.report = AMO.getReportName();
    this.page_size = 14;

    //Set up paginator

    this.paginator.ol.append(this.paginator.prev_li);
    for (var i=1; i<=this.paginator.num_buttons; i++) {
        var li = $("<li><a page='" + i + "' href='#'>" + i + "</a></li>");
        this.paginator.li.push(li);
        this.paginator.ol.append(li);
    }
    this.paginator.ol.append(this.paginator.next_li);

    var that = this;

    this.paginator.ol.click( function (e) {
        that.paginate.call(that, e);
    });

    this.tableEl.parent().after(this.paginator.ol);

    //Set up a BarTable if needed

    if (barColumns.length) {
        this.barTable = new BarTable({
            el: this.tableEl,
            columns: barColumns
        })
    }
}
PageTable.prototype.gotoPage = function(num) {
    set_loading(this.tableEl.parent());
    if (this.pages[num]) {
        if (num > 0) {
            $("tbody.selected", this.tableEl).removeClass("selected");
            $("li.selected", this.paginator.ol).removeClass("selected");
            $(this.pages[num]).addClass("selected");
            this.currentpage = num;

            //Update pagination
            if (!$("a[page='" + num + "']", this.paginator.ol).length) {
                if (num >= this.paginator.start + this.paginator.num_buttons) {
                    this.paginator.start = (num - this.paginator.num_buttons + 1);
                }
                if (num < this.paginator.start) {
                    this.paginator.start = num;
                }
                for (var i=0; i<this.paginator.num_buttons; i++) {
                    var li = this.paginator.li[i];
                    var a = $("a", li);
                    a.text(this.paginator.start + i);
                    a.attr("page", this.paginator.start + i);
                }
            }
            $("a[page='" + num + "']", this.paginator.ol).parent("li").addClass("selected");
            this.tableEl.parent().addClass("loaded");
        }
    } else {
        var that = this;
        Page.get({
            metric: this.report,
            num: num
        }, function (data) {
            that.addPage(data);
        });
    }
};
PageTable.prototype.addPage = function(data) {
    if (data.nodata) {
        this.tableEl.parent().addClass("loaded");
    }
    var stime = (new Date()).getTime();
    var page = ["<tbody>"],
        attr, val,
        row;

    for (var i=0; i<data.length; i++) {
        page.push("<tr>");
        row = data[i];
        if (row) {
            for (var c=0; c<this.columns.length; c++) {
                col = this.columns[c];
                val = AMO.StatsManager.getField(row, col.field);
                attr = " data-value='" + val + "'";
                if (col.format) {
                    val = this.format[col.format](val);
                }
                page.push('<td', attr, '>', val, '</td>');
            }
            page.push("</tr>");
        }
    }
    page.push("</tbody>");

    var fillerRow = "<tr class='fill''>" + repeat("<td>&nbsp;</td>", this.columns.length) + "</tr>";

    page.push(repeat(fillerRow, this.page_size - data.length));

    page = $(page.join(''));

    this.pages[data.page] = page;
    this.tableEl.append(page);
    if (this.barTable) {
        this.barTable.render(page);
    }
    this.gotoPage(data.page);
};
PageTable.prototype.paginate = function (e) {
    e.preventDefault();
    var tgt = $(e.target);
    if (tgt.attr("rel")) {
        var rel = tgt.attr("rel");
        if (rel == "next") {
            this.gotoPage(this.currentpage + 1);
        }
        if (rel == "prev") {
            this.gotoPage(this.currentpage - 1);
        }
    } else if (tgt.attr("page")) {
        var page = parseInt(tgt.attr("page"));
        this.gotoPage(page);
    }
}
PageTable.prototype.setColumns = function(cols) {
    var that = this;
    if (this.report in breakdown_metrics) {
        cols = $.map(cols, function(c) {
                c = breakdown_metrics[that.report] + "|" + c;
            return {field: c, format: 'number'};
        });
    }
    cols.unshift({field: 'date', format: 'date'});
    var thead = [];
    $.each(cols, function(i, c) {
        thead.push(
            "<th data-format='",
            c.format,
            "' data-field='",
            c.field,
            "'>");
        if (c.field.indexOf('|') > -1 ) {
            thead.push(AMO.StatsManager.getPrettyName(this.report, c.field.split('|').splice(1).join('|')));
        } else {
            thead.push(c.field[0].toUpperCase() + c.field.substr(1));
        }
        thead.push('</th>');
    });
    $("thead", this.tableEl).html(thead.join(''));
    this.columns = cols;
    this.pages = [];
    this.gotoPage(this.currentpage);
}

function BarTable(_cfg) {
    this.tableEl = _cfg.el;
    this.columns = _cfg.columns;
    this._cfg = _cfg;

    if (this.tableEl) {
        for (var i=0; i<this.columns.length; i++) {
            var col = this.columns[i];

            var valueColumn = col.valueColumn + i,
                insertAfter = (col.insertAfter || col.valueColumn) + i,
                ignore = _cfg.ignoreRows || col.ignoreRows || [],
                caption = col.caption || ''
                afterTh = $('thead tr th:nth-child(' + insertAfter + ')', this.tableEl),
                th = $('<th class="' + col.className + '">' + caption + '</th>'),
                scale = col.scale || 'linear';

            th.css({
                width: col.width
                });
            th.insertAfter(afterTh);

            col.th = th;

        }
    }
}
BarTable.prototype.render = function(tbody) {
    for (var i=0; i<this.columns.length; i++) {
        var col = this.columns[i];

        var valueColumn = col.valueColumn + i,
            insertAfter = (col.insertAfter || col.valueColumn) + i,
            ignore = this._cfg.ignoreRows || col.ignoreRows || [],
            scale = col.scale || 'linear';

        var tds = $('tr td:nth-child(' + valueColumn + ')', tbody);
        if (insertAfter == valueColumn) {
            var insertEls = tds;
        } else {
            var insertEls = $('tr td:nth-child(' + insertAfter + ')', tbody);
        }

        var maxVal = 0;
        var vals = [];
        for (var j=0; j<tds.length; j++) {
            if ($.inArray(j,ignore) < 0) {
                var td = $(tds[j]);
                if (td.getData('value')) {
                    var val = parseFloat(td.getData('value'));
                } else {
                    var val = parseFloat(td.text());
                }
                if (val > maxVal) {
                    maxVal = val;
                }
                vals.push(val);
            }
        }

        var maxWidth = col.th.width();

        for (var j=0; j<tds.length; j++) {
            var ia = insertEls[j];
            var td = $('<td class="' + col.className + '"></td>');

            if ($.inArray(j,ignore) < 0) {
                var bar = $('<div>&nbsp;</div>');
                var val = vals[j]
                if (val > 0) {
                    switch (scale) {
                        case 'log':
                            var wid = (Math.log(vals[j]) / Math.log(10)) / (Math.log(maxVal) / Math.log(10)) * 100;
                            break;
                        case 'linear':
                        default:
                            var wid = (vals[j] / maxVal) * 100;
                            break;
                    }
                } else {
                    wid = 0;
                }
                bar.css({
                    background: col.barColor,
                    width: wid + '%',
                });
                td.append(bar);
                $(ia).after(td);
            } else {
                $(ia).after(td);
            }
        }

    }
}
