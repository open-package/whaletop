# Releasing whaletop

## One-time setup

1. **Pages:** in the GitHub repo, open *Settings → Pages* and set *Source* to **GitHub Actions**.

2. **Maintainer field:** in *Settings → Secrets and variables → Actions → Variables*, add
   `DEB_MAINTAINER`, for example `open-package <maintainers@example.com>`. It becomes the
   `Maintainer:` line of the `.deb`.

3. **Signing key:** apt only accepts signed repositories. Create a key used only for this repo.
   Use a temporary `GNUPGHOME` so it never enters your personal keyring:

   ```sh
   export GNUPGHOME="$(mktemp -d)"
   gpg --batch --passphrase '' --quick-gen-key "whaletop apt signing <contact@hasan-amit.com>" ed25519 sign never
   gpg --list-keys            # note the fingerprint for your records
   gpg --armor --export-secret-keys > whaletop-apt-signing.private.asc
   gpg --armor --export        > whaletop-apt-signing.public.asc
   ```

   - **No passphrase:** the key only lives in an encrypted GitHub secret. To use one anyway,
     drop `--passphrase ''` and add the passphrase as the secret `APT_SIGNING_PASSPHRASE`.
   - **No expiry:** when an apt key expires, every user gets `apt update` errors until they
     re-download it by hand, which is why apt repositories normally use non-expiring keys.

   Add the **entire** contents of `whaletop-apt-signing.private.asc`, including the
   `-----BEGIN/END PGP PRIVATE KEY BLOCK-----` lines, as the repository secret `APT_SIGNING_KEY`
   (*Settings → Secrets and variables → Actions → New repository secret*).

   Back the private key up offline (a password manager or an encrypted drive), then remove the
   local copies:

   ```sh
   shred -u whaletop-apt-signing.private.asc
   rm -rf "$GNUPGHOME"; unset GNUPGHOME
   ```

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
   Or create the release in the GitHub web UI (*Releases → Draft a new release*, new tag
   `v0.2.0` on `main`, *Publish*). The workflow then attaches the files to that release instead
   of creating one. If *Release immutability* is turned on in the repo settings, published
   releases can't receive files afterwards, so use the tag push.
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
