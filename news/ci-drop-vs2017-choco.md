### Enhancements

* <news item>

### Bug fixes

* <news item>

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* Stop installing the Visual Studio 2017 Build Tools on every Windows CI
  job (`choco install visualstudio2017-workload-vctools`, ~280s per job).
  It existed solely to service `test_build_msvc_compiler[15.0]`, which
  exercises the `msvc_compiler` meta.yaml key deprecated in 2018. A survey
  of conda-forge shows only two frozen legacy runtime feedstocks still use
  that key (vs2008_runtime, last real commit 2018-01; vs2015_runtime, last
  real commit 2016-07); the actively-maintained successor (`vc-feedstock`)
  uses modern compiler activation. The test now skips when VS 2017 is not
  installed rather than being gated by a 280s CI install step.
