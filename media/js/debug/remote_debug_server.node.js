var html = require('fs').readFileSync(__dirname+'/remote_debug_viewer.html');
var http = require('http');
var url = require('url');
var console = require('console');

var server = http.createServer(function(req, res){
  res.end(html);
});

var port = +process.argv[2] || 8080;
console.log('logging to port ' + port);
server.listen(port);

var nowjs = require("now");
var everyone = nowjs.initialize(server);

//listener server
http.createServer(function (req, res) {
  res.writeHead(200, {'Content-Type': 'text/plain'});
  res.end();
  var msg = decodeURIComponent(url.parse(req.url).query);
  console.log(msg);
  var msgObj = JSON.parse(msg);
  if (msgObj.type == 'error') {
      everyone.now.showError(msg);
  } else {
      everyone.now.showLog(msg);
  }
}).listen(37767);
