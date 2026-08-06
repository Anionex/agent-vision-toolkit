# Security Policy

## Supported Versions

Until tagged releases are published, security fixes are made against the current `main` branch only. Users should reproduce a suspected issue against the latest revision before reporting it.

## Reporting a Vulnerability

Do not open a public issue for a suspected vulnerability.

Report it privately by emailing `davidyang042@gmail.com` with the subject `agent-vision-toolkit security report`. If GitHub private vulnerability reporting is available on the repository, you may use that channel instead.

Include, when relevant:

- the affected component and revision;
- the agent host, operating system, and runtime versions;
- the security impact and required preconditions;
- minimal reproduction steps or a controlled proof of concept;
- suggested mitigations, if known.

Never include live API keys, Authorization headers, private images, complete request bodies, or unrelated conversation content. Use placeholders and the smallest sanitized artifact that demonstrates the problem.

The maintainer will acknowledge the report as soon as practical, investigate it privately, and coordinate remediation and disclosure with the reporter.

## Security-Relevant Areas

Reports are especially useful for issues involving:

- forwarding or disclosure of authentication headers;
- accidental logging or persistence of request bodies, images, prompts, conversations, or credentials;
- exposure of the local proxy beyond its intended loopback interface;
- request-dialect confusion that sends image data to the wrong upstream;
- unsafe local file handling in the CLI tools or native extensions;
- dependency or extension behavior that crosses the documented trust boundary.

## Data Handling Expectations

The proxy is expected to send images only to the configured vision API, replace them with text descriptions before forwarding to the text-only upstream, and keep its description cache in memory. Logs must contain only operational metadata and must never contain request bodies, images, prompts, conversations, or API keys.
