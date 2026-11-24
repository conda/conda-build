### Bug fixes

* Fix `conda inspect channels` leaking a bare string into conda's global context (`_channels`), which made unrelated builds in the same process fail with `InvalidTypeError`. The subcommand's positional is renamed to `channel_name` to avoid colliding with conda's `channels`/`channel` config alias. (#6286)
