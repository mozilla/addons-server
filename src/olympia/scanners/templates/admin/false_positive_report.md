### Report

The [scanner result {{ result.id }}]({{ result.get_admin_absolute_url }}) reports matches of the following _{{ result.get_scanner_name }}_ rules:

{% for rule in result.matched_rules.all %}
- `{{ rule.name }}`
{% empty %}
(no matched rules)
{% endfor %}

However, it is not correct for the following reasons:

<!-- Please explain why you are reporting a false positive here. -->

### Metadata

| Name        | Value                           |
|-------------|---------------------------------|
| Add-on GUID | {{ result.version.addon.guid }} ([product page]({{ result.version.addon.get_absolute_url }})) |
| Version ID  | {{ result.version.id }} |
| Channel     | {{ result.version.get_channel_display }} |
| Scanner     | {{ result.get_scanner_name }} |

{% if not result.version %}
:warning: Some information is missing because there is no version attached to these results.
{% endif %}
{% if result.scanner == YARA %}
### Raw scanner results

<details>
<summary>show raw scanner results</summary>

```json
{{ result.get_pretty_results|safe }}
```
</details>
{% endif %}
