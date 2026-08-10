"""Endpoints, one of them over plain HTTP.

The loopback address is here because it is not the defect the rule is about,
and a rule that reports it makes every development setup noisy.
"""

BILLING = "http://billing.internal/v2/charge"
METRICS = "https://metrics.internal/v1/push"
LOCAL = "http://localhost:8080/health"
