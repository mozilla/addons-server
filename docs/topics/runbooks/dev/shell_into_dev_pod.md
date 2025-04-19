# Shell into a dev pod

## Steps

### Shell into bastion host

This will authenticate you for gcloud and open a shell into the bastion host.

```bash
gcloud auth login --update-adc
gcloud compute ssh --zone "us-west1-a" "bastion-us-west1" --project "moz-fx-bastion-nonprod-global" --tunnel-through-iap
```

### Shell into an available dev pod

This will reauthenticate your gcloud session and open a shell into the first available dev pod.

```{tip}
Bastion host sessions are stateful. Changes to kubectl config will persist
the next time you connect.
```

```bash
gcloud auth login
kubectl config use-context amo-dev
pod_name=$(kubectl get pods --output json | jq -r \
  '.items[]
  | select(.metadata.name
  | contains("deploy-uwsgi-amo-web"))
  | .metadata.name' \
  | head -n 1)
kubectl exec -it $pod_name -- bash
```

### Verify the pod is correct

```bash
cat /build-info.json
```

You should see image metadata similar to the following:

Expect a production target with the `latest` version, the tag deployed to dev.

```json
{
  "commit": "923382b977dd2b6c1085e310f26e927b82e7dc82",
  "version": "latest",
  "build": "https://github.com/mozilla/addons-server/actions/runs/14291850724",
  "target": "production",
  "source": "https://github.com/mozilla/addons-server"
}
```

Additionally, the `ENV` variable should return `dev`.

```bash
echo "env: $ENV"
```
