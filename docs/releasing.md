# Development and releases

## Development

```sh
git clone https://github.com/open-package/whaletop.git
cd whaletop
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

The tests use an in-memory Docker implementation and do not require a Docker daemon.

### Documentation

```sh
.venv/bin/pip install -e '.[docs]'
.venv/bin/mkdocs serve        # http://127.0.0.1:8000
```

The screenshots in `docs/assets/` are generated from demo data and require Google Chrome or
Chromium:

```sh
.venv/bin/python docs/screenshots.py
```

## Release pipeline

| Workflow | Trigger | Result |
|---|---|---|
| `ci.yml` | Push to `main`, pull request | Tests on Python 3.10 and 3.13, documentation build, and `build.yml` |
| `build.yml` | Called by `ci.yml` and `release.yml` | Builds the `.deb`, wheel and sdist, checks their names against `__version__`, installs and runs each. Publishes nothing. |
| `release.yml` | Tag `v*` | Tests, `build.yml`, PyPI upload, then the GitHub release |
| `pages.yml` | Completion of `release.yml`, documentation change on `main`, manual | Documentation and signed apt repository published to GitHub Pages |

`release.yml` publishes only after every artifact has been built and verified, and publishes
to PyPI, the only irreversible step, before creating the GitHub release. The apt repository is
rebuilt from the `.deb` assets of the GitHub releases, so it changes only after a release is
complete. As a result:

| A release fails in | Published | Recovery |
|---|---|---|
| `test` or `build` | Nothing | Fix the problem, move the tag to the fixed commit, push it again. The version number is unchanged. |
| `pypi` | Nothing | Fix the cause (usually the trusted-publisher configuration) and re-run the failed job. |
| `github-release` | PyPI only | Re-run the failed job. |

Because `ci.yml` runs `build.yml` on every push, packaging problems normally appear on `main`
before a tag is created.

The Pages site serves the documentation at the root and the apt repository under `dists/` and
`pool/`, with the public signing key at `whaletop.gpg`.

## Releasing a version

1. Update `__version__` in `src/whaletop/__init__.py`, commit and push to `main`. This is the
   only place the version is defined.
2. Wait for the `ci` workflow on that commit to pass, including the `build` job.
3. Tag the commit and push the tag:

    ```sh
    git tag v0.2.0
    git push origin v0.2.0
    ```

4. Monitor the workflows under *Actions*.

To move a tag after a failure in `test` or `build`:

```sh
git tag -d v0.2.0 && git push origin :refs/tags/v0.2.0
git tag v0.2.0 && git push origin v0.2.0
```

Releases should be started with a tag push. A release created in the GitHub web interface is
public before its files are built; the workflow attaches the files to it afterwards.

To republish the documentation and apt repository without a release, run the **pages** workflow
manually from the *Actions* tab.

## Repository configuration

These settings are required once per repository.

### GitHub Pages

*Settings → Pages → Source*: **GitHub Actions**.

### Package maintainer

Repository variable `DEB_MAINTAINER` (*Settings → Secrets and variables → Actions → Variables*),
in the form `Name <email@example.com>`. It is written to the `Maintainer` field of the `.deb`.

### apt signing key

apt only accepts signed repositories. Generate a dedicated key in a temporary keyring:

```sh
export GNUPGHOME="$(mktemp -d)"
gpg --batch --passphrase '' --quick-gen-key "whaletop apt signing <email@example.com>" ed25519 sign never
gpg --list-keys
gpg --armor --export-secret-keys > whaletop-apt-signing.private.asc
```

Store the complete contents of `whaletop-apt-signing.private.asc`, including the
`BEGIN` and `END` lines, as the repository secret `APT_SIGNING_KEY`. Keep an offline backup, then
remove the local copies:

```sh
shred -u whaletop-apt-signing.private.asc
rm -rf "$GNUPGHOME"; unset GNUPGHOME
```

- The key has no expiry. An expired key causes `apt update` to fail for all users until they
  download the key again.
- The key has no passphrase because it is stored only as an encrypted secret. To use a
  passphrase, omit `--passphrase ''` and store the passphrase as the secret
  `APT_SIGNING_PASSPHRASE`.
- Do not replace the key. Existing installations trust only the original public key.

### PyPI trusted publishing

Releases are uploaded with [trusted publishing](https://docs.pypi.org/trusted-publishers/); no
API token is stored. On PyPI, under *Account settings → Publishing*, register a GitHub publisher:

| Field | Value |
|---|---|
| PyPI project name | `whaletop` |
| Owner | `open-package` |
| Repository name | `whaletop` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

The PyPI account requires a verified email address and two-factor authentication. Optionally,
add required reviewers to the `pypi` environment (*Settings → Environments → pypi*) to approve
each upload.

## Building packages locally

```sh
MAINTAINER="Name <email@example.com>" packaging/build-deb.sh    # dist/whaletop_<version>_all.deb
python -m build                                                  # dist/*.whl, dist/*.tar.gz
packaging/build-apt-repo.sh dist/ apt/ <gpg-key-id>              # signed apt repository in apt/
```
