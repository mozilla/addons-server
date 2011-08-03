var html = require('fs').readFileSync(__dirname+'/remote_debug_viewer.html');
var http = require('http');
var url = require('url');

var server = http.createServer(function(req, res){
  res.end(html);
});
server.listen(8080);

var nowjs = require("now");
var everyone = nowjs.initialize(server);

//listener server
http.createServer(function (req, res) {
  res.writeHead(200, {'Content-Type': 'text/plain'});
  res.end();
  var error = url.parse(req.url).query;
  everyone.now.showError(error);
}).listen(37767);
