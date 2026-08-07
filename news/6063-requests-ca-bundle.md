### Enhancements

* <news item>

### Bug fixes

* Only pass through ``REQUESTS_CA_BUNDLE`` when it is set in the environment, matching ``SSL_CERT_FILE``. Setting it to an empty string broke TLS clients such as botocore. (#6063)

### Deprecations

* <news item>

### Docs

* Document ``REQUESTS_CA_BUNDLE`` as an inherited build environment variable. (#6063)

### Other

* <news item>
