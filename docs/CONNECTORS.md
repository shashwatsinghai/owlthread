# Built-in context connections

OwlThread 1.7.0 bundles browser sign-in for Cloudflare and GitHub. No separate MCP server or plugin needs to be downloaded. Select your OwlThread project, open **Connect**, click **Sign in with Cloudflare/GitHub**, complete provider approval in the browser, choose a discovered account/repository and import. GitHub asks you to enter the short device code shown in OwlThread. Imported snapshots appear in Raw captures, search and generated context briefs. Sign-in alone does not import data or grant an MCP client access. The import destination remains the project selected when sign-in started, even if you navigate elsewhere while approving.

**Open browser again** reopens a pending sign-in; **Cancel** stops it without saving late credentials. You can close the desktop while sign-in is pending. Discovery shows up to 100 accounts or public repositories. Empty discovery explains that no accessible resources were found. Manual tokens, resource IDs and exact read scopes remain under the collapsed **Advanced** section.

## Cloudflare

Browser sign-in uses Cloudflare's [official remote MCP service](https://developers.cloudflare.com/agents/model-context-protocol/cloudflare/servers-for-cloudflare/), public client registration and PKCE with a random loopback callback on `127.0.0.1`. OwlThread requests identity, account discovery, zone/DNS reads, Worker metadata and Pages metadata, plus renewal access. Only fixed GET operations run through the MCP service's execute tool. The selected account import reads zones, Workers and Pages; DNS requires an explicit zone ID in Advanced.

For manual setup, enter your Cloudflare account ID. It is a 32-character hexadecimal value, not an email or account name. Enter a zone ID when selecting DNS records. Create a narrowly scoped API token for the account/zone you intend to import, or keep the existing browser credential by leaving the token field blank.

The account ID selects zones, Workers and Pages. DNS reads use the exact zone ID independently; OwlThread does not infer that a supplied zone belongs to the supplied account. Scope the provider token to the intended zone.

| OwlThread read scope | Context imported | Cloudflare token access |
| --- | --- | --- |
| `zones.read` | Zone names, status and nameservers in the selected account | Zone / Zone / Read |
| `dns.read` | DNS record names, types, content, TTL and proxy status in the selected zone | Zone / DNS / Read |
| `workers.read` | Worker script metadata in the selected account | Account / Workers Scripts / Read |
| `pages.read` | Pages project names, domains and production branch | Account / Pages / Read |

These scopes import metadata and DNS values. They do not download Worker source code, secrets, deployment logs, page content or D1 rows. Cloudflare's [API token guide](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/) explains token creation and resource limits. The clients use the official [Zones](https://developers.cloudflare.com/api/resources/zones/methods/list/), [DNS records](https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/list/), [Workers scripts](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/methods/list/) and [Pages projects](https://developers.cloudflare.com/api/resources/pages/subresources/projects/methods/list/) endpoints.

## GitHub

Browser sign-in uses OwlThread's own registered OAuth app and GitHub's [device authorization flow](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps#device-flow). Its public Client ID is bundled; a Client Secret is not needed or included. It requests `read:user`, discovers public repositories and imports only the selected repository's metadata, issues and pull requests. It does not request the OAuth `repo` scope, which includes write access. Private repositories use the Advanced fine-grained token option.

For manual setup, enter one repository as `owner/name`, such as `example/project`. Enter a token that can read that repository. For a fine-grained token, grant repository Metadata read access and Issues/Pull requests read access only for the chosen scopes.

For a fork or custom distribution, register your own OAuth app at GitHub Developer settings: homepage is your product URL, callback can be `http://127.0.0.1:41789/oauth/github/callback`, enable Device Flow, keep wildcard matching off and token expiry on. Set the public ID using `OWLTHREAD_GITHUB_CLIENT_ID` or the one-time **Set up GitHub sign-in** controls if no ID is bundled. Device flow does not use the callback. Never bundle a client secret. Device-flow refresh requests use the public ID and protected refresh token.

| OwlThread read scope | Context imported |
| --- | --- |
| `repositories.read` | Repository description, default branch, topics and update metadata |
| `issues.read` | Issue title, body, state, link and timestamps; pull requests are excluded |
| `pull-requests.read` | Pull request title, body, state, link and timestamps |

This client does not clone repositories or import source files, comments, diffs, Actions logs or review threads. See GitHub's [fine-grained token guide](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens), [repository](https://docs.github.com/en/rest/repos/repos), [issue](https://docs.github.com/en/rest/issues/issues) and [pull request](https://docs.github.com/en/rest/pulls/pulls) APIs.

## Stored access and import limits

Provider tokens are stored separately from grants and protected using Windows user-scoped DPAPI. They are excluded from general settings snapshots, MCP responses and imported capture metadata. A token copied to another Windows account may become unavailable; the saved ciphertext remains until you replace it. A blank token field keeps the existing credential.

Provider context reads are fixed GET operations. Cloudflare's MCP transport and OAuth registration/token exchange use HTTPS POST to official fixed hosts; these calls do not enable external writes. Redirects are refused. Each response is bounded to 2 MB and each imported record to 64,000 characters. Issue/PR bodies are limited to 16,000 characters with an explicit truncation marker. A sync defaults to 25 records per chosen scope, up to 100 through MCP. It fetches the first page only and reports truncation; it is a bounded context snapshot, not a full account backup. Exact repeated snapshots are deduplicated, while changed records remain available as new raw evidence.

Access and refresh tokens renew before imports and stay in the same protected credential setting. Disconnect cancels pending sign-in and removes local credentials/resource choices without deleting imported captures. To revoke provider-side authorization too, use the provider's authorized-app settings; for GitHub use [OwlThread access](https://github.com/settings/connections/applications/Ov23lipL10mn453vuau8).

The connection status records the last actual provider check, caches successful verification for 15 minutes and invalidates it when local configuration changes. Being bundled or configured does not mean the account is connected. Provider errors preserve existing captures and show a safe retry reason.

For MCP clients, configure credentials in desktop Connect first, then call `test_integration_connection` and `sync_integration_context`. Tokens are never accepted through these MCP tools. The existing `configure_integration` tool changes local grants only; external account permissions must also permit the selected reads. Only Cloudflare and GitHub have setup controls. Other catalog entries are marked **Coming soon** and have no bundled context client or sign-in flow.

Provider snapshots may include private issue text or DNS values. They follow the same raw-memory retention and configured-model behavior as other explicitly imported captures; see the README's provider and storage descriptions. Local transport/fixture tests verify behavior and safety boundaries. Live access to your particular accounts is confirmed only by a successful Test connection using your credentials.
