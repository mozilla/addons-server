function WorkerPool(size) {
    workers = 0;
    jobs = [];

    this.queueJob = function(url, msg, cb, ctx) {
        var job = {"url": url, "msg": msg, "cb": cb, "ctx": ctx};
        jobs.push(job);
        if (workers < size) nextJob();
    };
    
    function nextJob() {
        if (jobs.length) {
            (function() {
                var job = jobs.shift(),
                    worker = new Worker(job.url);
                workers++;
                worker.addEventListener('message', function(e) {
                    if (job.cb.call(job.ctx, e.data, worker)) {
                        worker.terminate();
                        delete worker;
                        workers--;
                        nextJob();
                    };
                }, false);
                worker.postMessage(job.msg);
            })();
        }
    }
}

function AsyncCache(miss, hash) {
    cache = {};
    hash = hash || function(key) {
        return key.toString();
    }
    self = this;
    this.get = function(key, cb, ctx) {
        var k = hash(key);
        if (k in cache) {
            cb.call(ctx, cache[k]);
        } else {
            miss.call(ctx, key, function(val) {
                self.set(key, val);
                self.get(key, cb, ctx);
            });
        }
    };
    this.set = function(key, val) {
        cache[hash(key)] = val;
    };
}

function hashObj(o) {
    var hash = [];
    for (var i in o) {
        if (o.hasOwnProperty(i)) {
            hash.push(i);
        }
    }
    return hash.join('_');
}