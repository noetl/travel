# Guest Mode

Guest mode is the v1 default. Durable identity mapping lands with Firebase Auth later.

When Auth0 build variables are absent, the app intentionally stays usable as a
guest surface. The NoETL playbook workload receives no authenticated `user_uid`
in that mode.

When Auth0 is configured and the user signs in, Muno forwards the Auth0 `sub` as
`user_uid` in playbook workloads and attaches the access token to NoETL API
requests. Backend JWT enforcement is deliberately deferred.
