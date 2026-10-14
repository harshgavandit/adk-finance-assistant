# Verification evidence

Recorded on 14 October 2026 with Python 3.14.6 on Windows, using the locally
configured OpenAI `gpt-4o-mini` model. Credentials are excluded from the reports.

| Evidence | Result | What it establishes |
| --- | --- | --- |
| Regression suite | 12 passed | Configuration, concurrent/cross-process rate limits, expiry, failure handling, source rendering, and ADK admission blocking |
| `pip check` | Passed | Installed dependency requirements are compatible |
| Python syntax compilation | Passed | Application modules and verifier compile |
| [offline.json](offline.json) | Passed | Both agents import with the configured model, demo budget is consistent, admission works |
| [live.json](live.json) | Passed | Real OpenAI generation, profile tool execution, investment delegation and public search |
| [browser-budget.png](browser-budget.png) | Observed | ADK web chat called the finance tool and displayed the demo budget |

The live verifier observes both named tool calls in the delegated search path
through callback state. The investment result lists source URLs and the actual
search retrieval timestamp. It does not establish the accuracy of numeric
prices/rates on linked pages.

The local suite emitted two upstream warnings: a Python 3.14 typing deprecation
in `google-genai` and ADK's experimental function-declaration feature notice.
They did not fail the checks.

GitHub Actions runs offline checks with a dummy credential and no billable
provider requests. These reports capture a local run; they are not a guarantee
of future provider availability, deployment readiness, or load capacity.
