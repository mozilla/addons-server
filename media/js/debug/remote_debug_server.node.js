var fs = require('fs')
var http = require('http');
var url = require('url');
var now = require("now");

var port = +process.argv[2] || 37767;
var server = http.createServer(function(req, res){
    res.end(fs.readFileSync(__dirname+'/remote_debug_viewer.html'));
}).listen(port);;

console.log('logging to port ' + port);

var everyone = now.initialize(server);

var serverId = 0;

var servers = {};

everyone.now.servers = servers;

everyone.now.logError = function(m,f,l) {
  now.getGroup('dbg').now.showError(m,f,l);
};
everyone.now.log = function(msg) {
  now.getGroup('dbg').now.showLog(msg);
};

everyone.now.registerRemoteDebugger = function(username) {
  console.log('registered remote debugger');
  this.now.username = username;
  var that = this;
  now.getGroup('target').count(function (n) {that.now.showMsg(n + ' clients connected')});
  now.getGroup('dbg').addUser(this.user.clientId);
  now.getGroup('dbg').now.showMsg('new debugger online: ' + this.now.username);
};

everyone.now.registerRemoteServer = function(p, w, h) {
  var sname = '[' + p + ', ' + [w,h].join('x') + ']';
  var out = 'new server online ' + sname;
  this.now.target = true;
  this.now.id = serverId++;
  now.getGroup('target').addUser(this.user.clientId);
  now.getGroup('dbg').now.showMsg(out);
  servers[this.now.id] = sname;
  // everyone.now.servers[this.now.id] = sname;
};
everyone.now.msg = function(msg) {
  now.getGroup('dbg').now.showMsg(msg);
};
everyone.now.async = function(url) {
  now.getGroup('dbg').now.showAsync(url);
};
everyone.now.repl = function(code) {
  now.getGroup('target').now.doEval(code);
};
everyone.now.evalResp = function(msg) {
  now.getGroup('dbg').now.replBack(msg);
};