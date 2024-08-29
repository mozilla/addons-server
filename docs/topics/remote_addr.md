(remote_addr)=

# IP addresses

AMO records IP addresses for various user actions, allowing us to correlate
user activity to find malicious and abusive actors. 

## Processing

`SetRemoteAddrFromForwardedFor` middleware is responsible for processing the
various headers and meta information we receive and setting
`META['REMOTE_ADDR']` on the `request` object passed to each view.

The request flow is either:
Client -> CDN -> Load balancer -> WSGI proxy -> addons-server
or
Client -> CDN -> CDN shield -> Load balancer -> WSGI proxy -> addons-server
or
Client -> Load balancer -> WSGI proxy -> addons-server

Currently:
- CDN is CloudFront or Fastly
- CDN shield is an additional PoP on the CDN that request can go through
  (only enabled on Fastly)
- Load Balancer is GKE Ingress (GCP)
- WSGI proxy is nginx + uwsgi

CDN is set up to add a `X-Request-Via-CDN` header set to a secret value known
to us so we can verify the request did originate from the CDN.

If the request was shielded by the CDN it sets the `X-AMO-Request-Shielded`
header to `"true"`. This header should only be trusted if `X-Request-Via-CDN`
has been verified already.

Nginx converts `X-Request-Via-CDN` and `X-Forwarded-For` to
`HTTP_X_REQUEST_VIA_CDN` and `HTTP_X_FORWARDED_FOR` parameters, respectively.

The `X-Forwarded-For` header is potentially user input. When intermediary
servers in the flow described above add their own IP to it, they are always
appending to the list, so we can only trust specific positions starting
from the right, anything else cannot be trusted.

CDN always makes origin requests with a `X-Forwarded-For` header set to
"Client IP, CDN IP", so the client IP will be second to last for a CDN
request. If the request was shielded, the shield PoP IP will be added so
the client IP will be third to last.

On GCP, GKE Ingress appends its own IP to that header, resulting
in a value of "Client IP, CDN IP, GKE Ingress IP" (or
"Client IP, CDN IP, CDN Shield IP, GKE Ingress IP" for shielded requests),
so the client IP will be third to last, or fourth to last if there was a
CDN Shield.

We are no longer hosted on AWS, but it's worth noting that on AWS, the classic
ELB we were using did not make any alterations to `X-Forwarded-For`. For this
reason, we only shift the client IP position we look at to account for the 
Load Balancer if `DEPLOY_PLATFORM` environ variable is set to `"gcp"`.

If the request didn't come from the CDN and is a direct origin request, on
AWS we can use `REMOTE_ADDR`, but on GCP we'd get the GKE Ingress IP, and the
`X-Forwarded-For` value will be "Client IP, GKE Ingress IP", so the client IP
will be second to last.

## Recording

Through several older models in the code have a dedicated field for this, 
more recent implementations should use `IPLog`, which is automatically
populated when an `ActivityLog` action constant is defined with `store_ip` set
to `True` (note that if the `keep` property isn't defined, we don't keep the
activity forever and therefore ultimately delete the associated `IPLog`
instance as well)


