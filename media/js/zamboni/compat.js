$(function() {
    var chart = $('#chart'),
        data = JSON.parse(chart.attr('data-data')),
        total = chart.attr('data-total'),
        keys = JSON.parse(chart.attr('data-keys')),
        series = _.map(data, function(value, key) {
            return [keys[key], parseInt(value / total * 100)];
        });
console.log(JSON.stringify(series));

    var chart = new Highcharts.Chart({
        chart: {
            renderTo: 'chart'
        },
        title: '',
        plotOptions: {
            pie: { cursor: 'pointer' }
        },
        tooltip: {
            formatter: function() {
                return '<b>'+ this.point.name +'</b>: '+ this.y +' %';
            }
        },
        series: [{
            type: 'pie',
            data: series
        }]
    });
});
