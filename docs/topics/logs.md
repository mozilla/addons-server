# Logs

(logs)=

We have various types of logs with different purposes in AMO. The following
tables summarize their characteristics:


| | `ActivityLog` / `LogEntry` |
|-| -------------------------- |
|Type| Database entry |
|Purpose| Storing information about developers/reviewers/admin actions |
|Stores IP| Depending on the action |
|Stores user| Yes, explictly (mandatory) |
|Retention| A year to forever depending on the action |
|Access| Redash |

| | [Application logging](./development/logging.md) |
|-| ----------------------------------------------- |
|Type| JSON (MozLog [^1]) |
|Purpose| Tracing specific calls / debugging |
|Stores IP| Yes |
|Stores user | Yes, if applicable (automatically for authenticated requests) |
|Retention| 6 months |
|Access| [Google Log Explorer](https://mozilla-hub.atlassian.net/wiki/spaces/SRE/pages/27921597/AMO+Dev+Resources#Application-Logs) |

| | CDN logs |
|-| --------  |
|Type| HTTP access logs  |
|Purpose| Generic request logging  |
|Stores IP| Yes |
|Stores user| No |
|Retention| 3 months |
|Access| Google Cloud Storage Bucket |

[^1]: addons-server and addons-frontend both produce application logs through python `logging` and `pino` respectively, emitting them in the [MozLog format](https://wiki.mozilla.org/Firefox/Services/Logging). That gets sent to our application logging pipeline used by all Firefox services.
