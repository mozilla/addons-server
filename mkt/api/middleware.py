class CORSMiddleware(object):

    def process_response(self, request, response):
        # This is mostly for use by tastypie. Which doesn't really have a nice
        # hook for figuring out if a response should have the CORS headers on
        # it. That's because it will often error out with immediate HTTP
        # responses.
        if getattr(request, 'CORS', None):
            response['Access-Control-Allow-Origin'] = '*'
            options = [h.upper() for h in request.CORS]
            if not 'OPTIONS' in options:
                options.append('OPTIONS')
            if set(['PATCH', 'POST', 'PUT']).intersection(set(options)):
                # We will be expecting JSON in the POST so expect Content-Type
                # to be set.
                response['Access-Control-Allow-Headers'] = 'Content-Type'
            response['Access-Control-Allow-Methods'] = ', '.join(options)
        return response
