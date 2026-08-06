### Enhancements

* <news item>

### Bug fixes

* Activate the host and build environments in Windows build scripts when packaging a recipe named `conda`, matching Unix. Previously `build_env_setup.bat` omitted activation entirely for such recipes, so host `etc/conda/activate.d` scripts never ran. (#6069)
* Honor `build/activate_in_script: false` in Windows build scripts, matching Unix build scripts and Windows output scripts, which already respected it. (#6069)

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* <news item>
