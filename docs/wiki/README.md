# Wiki sources

`Adiona-Migration.md` and `Hospitality-Platform.md` are the source pages for the [GitHub wiki](https://github.com/noetl/travel/wiki/Adiona-Migration). Publish through the separate `noetl/travel.wiki.git` repository, preserving unrelated pages and adding navigation entries only when absent. These pages describe the unmerged migration branch and its validation limits.

`playbook-profile.md` is the source for the wiki's
[Playbook: profile](https://github.com/noetl/travel/wiki/playbook-profile) page, a mirror of
[`docs/runbooks/profile-handling.md`](../runbooks/profile-handling.md) with wiki-style links.
Publish it as `playbook-profile.md` and add, under **Architecture** in `_Sidebar.md` after
`Playbook: calendar/list`:

```markdown
- [Playbook: profile](playbook-profile)
```
