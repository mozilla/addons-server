// FormData that works everywhere
// This abstracts out the nifty new FormData object in FF4, so that
// non-Firefox 4 browsers can take advantage of it.  If the user
// is using FF4, it will use FormData.  If not, it will construct
// the headers manually.
//
// ONLY DIFFERENCE: You don't create your own xhr object.
//
// Example:
//   var fd = z.FormData();
//   fd.append("test", "awesome");
//   fd.append("afile", fileEl.files[0]);
//   fd.xhr.setHeader("whatever", "val");
//   fd.open("POST", "http://example.com");
//   fd.send(); // same as above


(function( ) {
    var hasFormData = (typeof FormData != "undefined");

    z.FormData = function(){
        this.fields = {};
        this.xhr = new XMLHttpRequest();
        this.boundary = "z" + (new Date().getTime()) + "" + Math.floor(Math.random() * 10000000);

        if (hasFormData) {
            this.formData = new FormData();
        } else {
            this.output = "";
        }

        this.append = function(name, val) {
            if (hasFormData) {
                this.formData.append(name, val);
            } else {
                if(typeof val == "object" && "fileName" in val) {
                    this.output += "--" + this.boundary + "\r\n";
                    this.output += "Content-Disposition: form-data; name=\"" + name.replace(/[^\w]/g, "") + "\";";

                    // Encoding trick via ecmanaut (http://bit.ly/6p30c5)
                    this.output += " filename=\""+unescape(encodeURIComponent(val.fileName)) +"\";\r\n";
                    this.output += "Content-Type: " + val.type;

                    this.output += "\r\n\r\n";
                    this.output += val.getAsBinary();
                    this.output += "\r\n";
                } else {
                    this.output += "--" + this.boundary + "\r\n";
                    this.output += "Content-Disposition: form-data; name=\""+name+"\";";

                    this.output += "\r\n\r\n";
                    this.output += "" + val; // Force it into a string.
                    this.output += "\r\n";
                }
            }
        };

        this.open = function(mode, url, bool, login, pass) {
            this.xhr.open(mode, url, bool, login, pass);
        };

        this.send = function() {
            if (hasFormData) {
                this.xhr.send(this.formData);
            } else {
                content_type = "multipart/form-data;boundary=" + this.boundary;
                this.xhr.setRequestHeader("Content-Type", content_type);

                this.output += "--" + this.boundary + "--";
                this.xhr.sendAsBinary(this.output);
            }
        };
    };
})();

