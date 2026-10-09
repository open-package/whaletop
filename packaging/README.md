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

4. **PyPI** (trusted publishing, so there's no API token to create or store):
   1. Create an account at https://pypi.org/account/register/ and turn on two-factor
      authentication, which PyPI requires before you can publish.
   2. Open https://pypi.org/manage/account/publishing/ and, under *Add a new pending publisher*,
      choose **GitHub** and fill in:

      | Field | Value |
      |---|---|
      | PyPI Project Name | `whaletop` |
      | Owner | `open-package` |
      | Repository name | `whaletop` |
      | Workflow name | `release.yml` |
      | Environment name | `pypi` |

   The first successful release creates the `whaletop` project on PyPI under your account, and
   the pending publisher becomes a normal one. GitHub creates the `pypi` environment
   automatically on the first run. You can optionally add yourself as a required reviewer
   (*Settings → Environments → pypi*) so every PyPI upload waits for your approval.

## Releasing a version

1. Bump `__version__` in `src/whaletop/__init__.py` and commit to `main`.
2. Tag and push:
   ```sh
   git tag v0.2.0
   git push origin v0.2.0
   ```
3. `release.yml` runs the tests, checks that the tag matches `__version__`, builds
   `whaletop_<version>_all.deb` and attaches it to a GitHub Release. It then builds the wheel
   and sdist, attaches them to the same release and publishes them to PyPI.
4. `apt-repo.yml` then rebuilds the apt repository from every release's `.deb`, signs it, and
   publishes it to `https://open-package.github.io/whaletop/`.

To republish the apt repo without a new release (for example after fixing the signing secret),
run the **apt-repo** workflow by hand from the *Actions* tab.

PyPI never accepts the same version twice, even after a deletion. If a release fails after the
PyPI upload, fix the problem and release a new version number.

## Building locally

```sh
MAINTAINER="Your Name <you@example.com>" packaging/build-deb.sh     # -> dist/whaletop_<v>_all.deb
packaging/build-apt-repo.sh dist/ site/ <gpg-key-id>               # signed repo in site/
```

The `.deb` bundles its pure-Python dependencies under `/usr/lib/whaletop/vendor`, because the
versions Debian and Ubuntu ship are far too old. It's `Architecture: all` and works on any
release with Python 3.10+ (Ubuntu 22.04+, Debian 12+).
