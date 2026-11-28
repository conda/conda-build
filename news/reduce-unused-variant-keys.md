### Enhancements

* Speed up rendering `meta.yaml` recipes with large variant configs: keys that the recipe cannot use are no longer exploded into the variant matrix. They keep the value they would have in the first variant, so `config.variants` and `config.input_variants` only hold one value for them. For example, the conda-forge global pinning no longer expands into tens of thousands of variants for a recipe that only uses a couple of keys. Tools that read other keys from the rendered variants can keep them fully exploded with the new `explode_variant_keys` config option.

### Bug fixes

* <news item>

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* <news item>
