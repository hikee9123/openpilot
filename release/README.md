# openpilot releases

```
## release checklist

### Go to staging
- [ ] make a GitHub issue to track release
- [ ] create release master branch
- [ ] update RELEASES.md
- [ ] bump version on master: `common/version.h` and `RELEASES.md`
- [ ] build new userdata partition from `release3-staging`
- [ ] post on Discord, tag `@release crew`

Updating staging:
1. either rebase on master or cherry-pick changes
2. run this to update: `BRANCH=devel-staging release/build_devel.sh`
3. build new userdata partition from `release3-staging`

### Go to release
- [ ] before going to release, test the following:
  - [ ] update from previous release -> new release
  - [ ] update from new release -> previous release
  - [ ] fresh install with `openpilot-test.comma.ai`
  - [ ] drive on fresh install
  - [ ] no submodules or LFS
  - [ ] check sentry, MTBF, etc.
  - [ ] stress test passes in production
- [ ] publish the blog post
- [ ] `git reset --hard origin/release3-staging`
- [ ] tag the release: `git tag v0.X.X <commit-hash> && git push origin v0.X.X`
- [ ] create GitHub release
- [ ] final test install on `openpilot.comma.ai`
- [ ] update factory provisioning
- [ ] close out milestone and issue
- [ ] post on Discord, X, etc.
```

## Fork release builds

`build_release.sh` can build and optionally push a release branch to a fork-owned remote.

Example:

```bash
RELEASE_BRANCH=release3 \
RELEASE_REMOTE=git@github.com:hikee9123/openpilot.git \
BUILD_DIR=/data/openpilot-release3 \
PANDA_DEBUG_BUILD=1 \
PUSH=1 \
release/build_release.sh
```

`BUILD_DIR` defaults to `/data/openpilot-release-$RELEASE_BRANCH`. `RELEASE_REMOTE` defaults to the source checkout's `origin`. Push is skipped unless `PUSH=1` is set. Release commit identity defaults to local `git config user.name` and `git config user.email`, and can be overridden with the standard `GIT_AUTHOR_*` and `GIT_COMMITTER_*` environment variables.
