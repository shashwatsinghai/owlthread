# Built-in context connections

OwlThread 1.6.0 bundles Cloudflare and GitHub clients. No separate MCP server or plugin needs to be downloaded to use these clients. Open **Connect**, choose a provider, enter its resource details and token, select read scopes, save, then use **Test access** and **Import context**. Imported snapshots are saved in the project selected at setup and appear in Raw captures, search and generated context briefs. They do not automatically change external resources.

## Cloudflare

Enter your Cloudflare account ID. It is a 32-character hexadecimal value, not an email or account name. Enter a zone ID when selecting DNS records. Create a narrowly scoped API token for the account/zone you intend to import.

The account ID selects zones, Workers and Pages. DNS reads use the exact zone ID independently; OwlThread does not infer that a supplied zone belongs to the supplied account. Scope the provider token to the intended zone.

| OwlThread read scope | Context imported | Cloudflare token access |
| --- | --- | --- |
| `zones.read` | Zone names, status and nameservers in the selected account | Zone / Zone / Read |
| `dns.read` | DNS record names, types, content, TTL and proxy status in the selected zone | Zone / DNS / Read |
| `workers.read` | Worker script metadata in the selected account | Account / Workers Scripts / Read |
| `pages.read` | Pages project names, domains and production branch | Account / Pages / Read |

These scopes import metadata and DNS values. They do not download Worker source code, secrets, deployment logs, page content or D1 rows. Cloudflare's [API token guide](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/) explains token creation and resource limits. The clients use the official [Zones](https://developers.cloudflare.com/api/resources/zones/methods/list/), [DNS records](https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/list/), [Workers scripts](https://developers.cloudflare.com/api/resources/workers/subresources/scripts/methods/list/) and [Pages projects](https://developers.cloudflare.com/api/resources/pages/subresources/projects/methods/list/) endpoints.

## GitHub

Enter one repository as `owner/name`, such as `example/project`. Enter a token that can read that repository. For a fine-grained token, grant repository Metadata read access and Issues/Pull requests read access only for the chosen scopes.

| OwlThread read scope | Context imported |
| --- | --- |
| `repositories.read` | Repository description, default branch, topics and update metadata |
| `issues.read` | Issue title, body, state, link and timestamps; pull requests are excluded |
| `pull-requests.read` | Pull request title, body, state, link and timestamps |

This client does not clone repositories or import source files, comments, diffs, Actions logs or review threads. See GitHub's [fine-grained token guide](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens), [repository](https://docs.github.com/en/rest/repos/repos), [issue](https://docs.github.com/en/rest/issues/issues) and [pull request](https://docs.github.com/en/rest/pulls/pulls) APIs.

## Stored access and import limits

Provider tokens are stored separately from grants and protected using Windows user-scoped DPAPI. They are excluded from general settings snapshots, MCP responses and imported capture metadata. A token copied to another Windows account may become unavailable; the saved ciphertext remains until you replace it. A blank token field keeps the existing credential.

All provider calls use HTTPS GET requests to fixed official API hosts. Redirects are refused. Each response is bounded to 2 MB and each imported record to 64,000 characters. Issue/PR bodies are limited to 16,000 characters with an explicit truncation marker. A sync defaults to 25 records per chosen scope, up to 100 through MCP. It fetches the first page only and reports truncation; it is a bounded context snapshot, not a full account backup. Exact repeated snapshots are deduplicated, while changed records remain available as new raw evidence.

The connection status records the last actual provider check, caches successful verification for 15 minutes and invalidates it when local configuration changes. Being bundled or configured does not mean the account is connected. Provider errors preserve existing captures and show a safe retry reason.

For MCP clients, configure credentials in desktop Connect first, then call `test_integration_connection` and `sync_integration_context`. Tokens are never accepted through these MCP tools. The existing `configure_integration` tool changes local grants only; external account permissions must also permit the selected reads. Other catalog entries currently have no bundled context client.

Provider snapshots may include private issue text or DNS values. They follow the same raw-memory retention and configured-model behavior as other explicitly imported captures; see the README's provider and storage descriptions. Local transport/fixture tests verify behavior and safety boundaries. Live access to your particular accounts is confirmed only by a successful Test connection using your credentials.
