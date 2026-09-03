# Security Policy

## Supported Versions

Security fixes are applied to the `master` branch and the latest published
release, when releases are published.

## Reporting a Vulnerability

Please do not report security vulnerabilities in a public issue. Open a private
security advisory on GitHub if the repository enables GitHub Security Advisories.
If private advisories are unavailable, contact the maintainers through the
private contact method configured for this repository and include:

- a clear description of the issue and its impact;
- affected versions, files, and configuration;
- reproducible steps or a minimal proof of concept;
- any suggested mitigation.

We will acknowledge reports, keep the report private while investigating, and
publish remediation details after a fix is available.

## Deployment Notes

Do not expose the MCP HTTP/SSE transport, Qdrant, SearXNG, or Reader services
to an untrusted network without authentication and network restrictions. Keep
`.env` private and replace all example secrets before deployment.
