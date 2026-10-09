# Releasing whaletop

## One-time setup

1. **Pages:** in the GitHub repo, open *Settings → Pages* and set *Source* to **GitHub Actions**.

2. **Maintainer field:** in *Settings → Secrets and variables → Actions → Variables*, add
   `DEB_MAINTAINER`, for example `open-package <maintainers@example.com>`. It becomes the
   `Maintainer:` line of the `.deb`.

3. **Signing key:** apt only accepts signed repositories. Create a key used only for this repo,
   without a passphrase, since it lives only in a GitHub secret:

   ```sh
   export GNUPGHOME="$(mktemp -d)"          # keep it out of your personal keyring
   gpg --batch --passphrase '' --quick-gen-key "whaletop apt signing <maintainers@example.com>" ed25519 sign 5y
   gpg --armor --export-secret-keys > whaletop-signing-key.asc
   gpg --armor --export > whaletop-signing-key.pub.asc
   ```

   Add the contents of `whaletop-signing-key.asc` as the repository secret `APT_SIGNING_KEY`
   (*Settings → Secrets and variables → Actions → Secrets*). Store the file somewhere safe
   offline, then delete it and the temporary `GNUPGHOME`.

   If you'd rather protect the key with a passphrase, add it as the secret
   `APT_SIGNING_PASSPHRASE`.

   Keep the same key for the life of the repository. Users have its public half installed, and
   changing it breaks `apt update` for every existing user.

## Releasing a version

1. Bump `__version__` in `src/whaletop/__init__.py` and commit to `main`.
2. Tag and push:
   ```sh
   git tag v0.2.0
   git push origin v0.2.0
   ```
3. `release.yml` runs the tests, checks that the tag matches `__version__`, builds
   `whaletop_<version>_all.deb` and attaches it to a GitHub Release.
4. `apt-repo.yml` then rebuilds the apt repository from every release's `.deb`, signs it, and
   publishes it to `https://open-package.github.io/whaletop/`.

To republish the apt repo without a new release (for example after fixing the signing secret),
run the **apt-repo** workflow by hand from the *Actions* tab.

## Building locally

```sh
MAINTAINER="Your Name <you@example.com>" packaging/build-deb.sh     # -> dist/whaletop_<v>_all.deb
packaging/build-apt-repo.sh dist/ site/ <gpg-key-id>               # signed repo in site/
```

The `.deb` bundles its pure-Python dependencies under `/usr/lib/whaletop/vendor`, because the
versions Debian and Ubuntu ship are far too old. It's `Architecture: all` and works on any
release with Python 3.10+ (Ubuntu 22.04+, Debian 12+).
