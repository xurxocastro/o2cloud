# Security Policy

## Reporting a vulnerability

If you believe you have found a security vulnerability in `o2cloud`, please report it privately.

- Preferred: open a private advisory through **GitHub Security Advisories** ("Report a vulnerability"
  on the repository's Security tab).
- Alternatively, contact the maintainers privately (see the repository's contact details).

Please do not open a public issue for security-sensitive reports. Include a clear description, steps to
reproduce, and the affected version. **Never include real credentials** (cookies, tokens,
`JSESSIONID`, passwords, or personal data) in a report; redact them.

We aim to acknowledge reports promptly and to coordinate a fix and disclosure timeline with you.

## Secrets and data handling

- Credentials are stored only in the OS keyring (service `o2cloud:<profile>`) or supplied through
  `O2CLOUD_*` environment variables. They are **never** written to files, logs, or this repository.
- Log output and the `--json` error envelope are passed through a secret redactor so that tokens
  cannot leak into stdout/stderr.
- TLS verification is enabled for all requests.

## Legal and interoperability notice

`o2cloud` is an **unofficial, personal interoperability client**. It is not affiliated with,
endorsed by, or supported by O2, Telefónica, or Funambol.

- It is intended for an account owner to access **their own data** in their own O2 Cloud account.
- It communicates with **undocumented endpoints** that were reverse-engineered from observed traffic;
  these may change or break at any time without notice.
- You are responsible for ensuring that your use complies with **O2's Terms of Service** and any
  applicable law. Use it at your own risk.
- The tool performs no bulk or abusive access and stores no credentials in the repository. It operates
  at app-like request rates against a single account.
