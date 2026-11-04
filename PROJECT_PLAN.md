# Listening Dashboard: Project Plan

Status: Milestones 1-3 implemented; persistent listening and commands are ready for review.
Last updated: 2026-11-04.

## 1. Purpose and agreed direction

Build a personal web dashboard for exploring music listening recorded by Last.fm. It must be useful to its owner alone, with private friend comparisons added after the personal experience works.

The project balance is **60% learning and 40% getting a working application quickly**. The developer has some Python experience and wants to learn practical software engineering through small, working increments.

Agreed requirements:

- Last.fm is the initial source. Spotify listening is recorded through the user's Last.fm connection; a direct Spotify API integration is unnecessary for the MVP.
- Scrobbling has been connected and confirmed working. The account is starting fresh; old Spotify history must not be assumed available.
- The interface is a dashboard for exploration rather than a Wrapped-style slideshow.
- Build and use the personal version on the user's computer first. Deployment and friend features follow later.
- Include taste statistics and listening volume. Estimated minutes are acceptable; measured listening time is unavailable from the planned source.
- Implement one milestone at a time, explaining its behavior, relevant concepts, and acceptance checks.

The stack and implementation details below are the recommended baseline. Revisit choices when evidence exposes a concrete problem and record significant changes and their reasons.

## 2. Personal MVP

Support one configured Last.fm profile and calendar-month selection.

| Capability | Expected behavior |
| --- | --- |
| Monthly overview | Recorded plays and top artists, tracks, and albums for the selected month. |
| Daily activity | Recorded plays per day, displayed as a chart with an accessible table or text equivalent. |
| Estimated minutes | Sum known track durations across recorded plays; label the result as an estimate and show duration coverage. |
| Month selection | Current partial month and earlier months for which history has been imported. |
| Comparisons | Compare completed months when both have data. Avoid partial-month versus full-month comparisons. |
| Manual refresh | Import available records without duplicating them. Show refresh status and last successful refresh time. |
| Honest empty states | Distinguish no recorded listening, history not imported, incomplete import, and provider failure. |

Make the dashboard useful with a few recorded plays. Do not reconstruct unavailable historical months. Use a layout suitable for desktop and narrow screens; remote phone access is outside the local milestone.

### Metric definitions

- **Recorded play:** a timestamped Last.fm scrobble. This does not prove an entire track was heard. Exclude currently-playing entries without a recorded timestamp.
- **Month:** calendar month in Europe/Stockholm. Store timestamps in UTC, convert local month boundaries to UTC, and filter start-inclusive/end-exclusive. Account for daylight-saving changes and provider boundary semantics.
- **Rankings:** counts of recorded plays in the selected month. Equal counts are ties; use alphabetical ordering for stable display. A provider's rolling top-items chart is not an exact calendar-month chart.
- **Identity:** preserve source names and optional stable identifiers. Do not fuzzy-merge remasters, live versions, collaborations, or similarly named artists in the MVP.
- **Albums:** use the album associated with the listen. Missing albums still contribute to total plays and artist/track rankings; exclude them from named-album rankings and show the missing-record count.
- **Estimated minutes:** sum positive, known track durations in milliseconds for eligible plays, divide by 60,000, and round only for display. Exclude missing or zero durations rather than inventing values.
- **Duration coverage:** percentage of recorded plays with a usable duration. Describe the minute estimate as covering those plays. With no usable durations, display unavailable rather than zero minutes.
- **Limitations:** source records may have gaps, duplicates, and incomplete tracking. Never describe these statistics as an exact account of all listening or Spotify's official Wrapped.

## 3. Technology and architecture

### Recommended stack and alternatives

| Area | Recommendation | Reason and trade-off |
| --- | --- | --- |
| Backend | Python and Django 5.2 LTS, latest supported patch at setup | Models, migrations, templates, testing, and authentication fit together. More initial concepts than a dashboard-only framework, but useful foundations for the planned website. Check Python compatibility and pin the environment in milestone 1. |
| Frontend | Django templates, HTML, CSS, and small amounts of JavaScript | Learn browser fundamentals while keeping one application. A separate React frontend adds tooling and interface coordination before there is a demonstrated need. |
| Charts | Chart.js | Interactive charts within ordinary pages. Calculate statistics in Python and send display-ready data to chart code. |
| Database | SQLite locally through Django's ORM | Minimal setup for one user. Evaluate PostgreSQL and migration checks before hosted, concurrent access. |
| Authentication | No account flow for the localhost-only personal version; Django session authentication before hosted access | Keep early work focused. A Last.fm username is data selection, not authentication or proof of account ownership. |
| Integration | Last.fm API, called from Python | Retrieve dated history and track metadata. Keep API credentials outside browser code and Git. |
| AI | Optional after the personal MVP | Evaluate a specific discovery benefit after a working baseline and useful listening history exist. |

Streamlit is a reasonable alternative for quickly building a Python data exploration tool. Django is preferred for learning general web development and supporting custom account/group workflows. FastAPI is a reasonable API-focused alternative, but requires assembling more application features and choosing a frontend approach.

### Component boundaries

Use one repository, one Django project, and initially one listening application. Separate responsibilities within that application:

1. **Views and templates:** validate month selections, request calculated results, and render the dashboard.
2. **Statistics functions:** calculate rankings, daily activity, comparisons, and estimates independently of external API calls.
3. **Last.fm client and importer:** fetch paginated history, translate responses, and manage refresh status.
4. **Models and database:** persist listening records, cached metadata, and import status through Django's ORM.

Data flow: manual refresh -> Python Last.fm client -> validation and persistence -> statistics functions -> Django page -> charts and tables.

Follow Django's conventional project structure, adding small integration and statistics modules beside models, views, templates, static assets, and tests. Defer a generic provider framework, public application API, background queue, Redis, and separate services.

### Main data entities

| Entity | Responsibility |
| --- | --- |
| Listening profile | Last.fm username, needed display information, and reporting timezone. No groups or memberships yet. |
| Track | Source identity and display metadata, optional identifiers, cached duration, and metadata-fetch status. |
| Recorded listen | Profile, track, UTC source timestamp, and album information associated with that listen. |
| Sync state | Requested/imported ranges, attempt and success times, completion status, and a safe error summary. Import coverage is distinct from actual listening coverage. |

Imports must be idempotent. For the MVP, identify an observed event by profile, UTC timestamp, artist name, and track name. Normalize consistently for keys while preserving display names. Timestamp alone is insufficient. Exact duplicate source entries collapse under this policy; document that limitation and do not claim to detect all duplicates or source edits.

### External requests and failure handling

- Use documented methods, finite timeouts, pagination, and bounded retries for temporary errors. Respect rate limits; do not retry invalid credentials indefinitely.
- Fetch requested history and needed metadata. Cache known durations and temporarily cache unsuccessful metadata lookups to avoid a call for every play.
- Start with a management command, then expose the same importer through a manual-refresh action in the local dashboard. Keep network calls outside database transactions.
- Preserve progress without marking incomplete ranges successful. Interrupted imports retain valid records, show incomplete status, and support safe retries.
- Keep existing statistics visible when Last.fm is unavailable, with stale/incomplete status.
- Imports are additive in the MVP. Historical deletions or edits on Last.fm are not automatically reconciled. Document a local reset-and-reimport procedure before relying on imported history.
- Enforce a bounded data-storage budget before persistent imports. Last.fm's terms currently specify a 100 MB Reasonable Usage Cap. Include caches in accounting and stop visibly before exceeding the budget; do not silently delete history. Review retention before an indefinite archive or adding friends.

## 4. Milestones and acceptance checks

Each milestone delivers a runnable increment, a focused explanation, and a short verification checklist. Finish and review one before expanding scope.

| Milestone | Deliverable and learning focus | Acceptance checks |
| --- | --- | --- |
| 1. Local dashboard skeleton | Python environment, Django project, month selector, and synthetic sample data. Learn request -> view -> template, project structure, and local startup. | Documented startup works on this Windows machine. Sample rankings, a partial-month label, and an empty state render. No Last.fm key is required. |
| 2. Last.fm integration | Small API client and read-only management command. Learn HTTP, JSON, environment configuration, pagination, and error handling. | Fetch timestamped plays and exclude now-playing entries. Exercise pagination, empty history, invalid credentials, and temporary failures with synthetic responses or mocks. No secrets in output. |
| 3. Reliable storage | Models, migrations, history persistence, and metadata caching through the reusable importer. Learn relational data, import keys, and retries. | Repeat imports add no duplicates; separate tracks at one timestamp survive; interrupted imports remain incomplete and can retry; enforce the storage budget. |
| 4. Monthly dashboard | Replace samples with monthly calculations, charts, duration coverage, and manual refresh. Learn aggregation, timezones, safe rendering, and chart integration. | Known examples produce expected rankings/daily counts. Verify month boundaries, missing albums/durations, zero coverage, partial months, completed-month comparisons, and refresh failures. |
| 5. Personal MVP review | Use accumulated real history, review usability/accessibility, and complete setup/limitation documentation. Learn practical debugging and feature evaluation. | Owner can refresh and explore a month without code edits. Check totals against the same dated source records. Core checks pass and setup is reproducible; acknowledge source gaps. |

Bind the development application to localhost. Remote access is a separate deployment task.

## 5. Engineering and learning practices

### The 60/40 approach

Updated working agreement: alternate implementing small pieces. The learner
must write meaningful Python logic and tests; explanations around code written
entirely by the assistant do not satisfy this goal. The assistant must leave
the learner's assigned piece for them to implement. This is also a portfolio
project: use coherent tested commits and document actual decisions and learning.
See CONTRIBUTING.md.

- Explain a milestone's behavior, the few new concepts involved, and acceptance checks before implementation.
- Build a thin working path early, then explain and improve it. Avoid lengthy prerequisite courses and large code dumps.
- Explain important functions, data flow, and trade-offs in small pieces. Include one relevant learner change or debugging exercise when useful.
- Use framework conventions and established libraries to save time. Add dependencies only for concrete needs.
- Close with what works, how it was verified, what was learned, and limitations. Treat 60/40 as a guiding balance rather than an exact time quota.

### Git workflow

Keep main runnable. Use a short-lived branch per milestone or focused change, with small descriptive commits. Review diffs and relevant checks before merging. Add lightweight pull requests and CI when a remote repository is used; Gitflow and a separate development branch are unnecessary.

Commit migrations and dependency specifications. Ignore secrets, virtual environments, local databases, downloaded personal data, logs, and generated artifacts. Commit only synthetic listening fixtures.

### Testing

Use Django's built-in test runner initially. Test calculations with small explicit examples; mock HTTP responses so normal tests do not depend on Last.fm.

Prioritize duplicate imports, pagination, retries, UTC/local month boundaries including daylight-saving transitions, ranking ties, partial imports, missing metadata, and duration arithmetic. Add focused view tests for invalid month selection, empty/error states, and refresh handling. Check charts and narrow-screen layout manually initially; introduce browser automation when interactions justify it.

### Documentation

Keep this document as the planning baseline. During implementation, add a README with setup/run instructions, dependency versions, environment variable names without values, verification commands, and metric-definition links. Record major architectural changes with a short decision and rationale.

## 6. Security, privacy, and provider obligations

- The local version serves its configured owner. Keep credentials outside Git; sanitize provider errors and logs.
- Preserve Django's escaping and CSRF protections. Serialize chart data safely rather than embedding untrusted music metadata as executable JavaScript.
- Before hosted access, add authentication, ownership checks, secure cookies, HTTPS configuration, backups, and data deletion behavior.
- Friends must explicitly join and consent to comparisons. Public Last.fm visibility does not imply consent to group publication.
- Include Last.fm attribution and source links. Respect caching requirements, rate limits, and the documented usage cap.
- Review current terms before deployment. Last.fm clause 2.7 currently requires prior written approval for public access to pages using its web services. Noncommercial status alone does not establish permission to publish. Resolve applicable requirements before hosted access or external distribution. Do not contact anyone without user authorization.
- Do not assume Spotify API content can be processed by AI. Future external AI processing requires checking data permissions and model-provider terms, explicit user choice, and minimal information disclosure.

## 7. After the personal MVP

**Deployment:** settle hosting and cost limits, evaluate PostgreSQL, configure authentication/backups, and review provider publication requirements. Add simple operational error reporting and health checks appropriate to the host.

**Friends:** application accounts, verified profile linking, private groups, invitations, membership permissions, and listening/taste comparisons. Keep personal statistics useful without groups. Define fair comparisons for unequal tracking coverage before competitive rankings.

**Music discovery:** start with Last.fm similar artists and community tags. Filter candidates against recorded history; distinguish unfamiliar-to-the-app from unknown-to-the-user. Evaluate optional AI for interpreting preferences, reranking verified candidates, and grounded explanations. Compare usefulness with a simpler baseline before accepting cost and complexity.

**Other deferred work:** annual presentations, public sharing, scheduled imports, direct Spotify integration, fuzzy metadata reconciliation, and advanced recommendation models. Reassess priorities after real use.

## 8. Sources and remaining checks

Capabilities and policies can change. Recheck relevant documentation when implementing a dependency.

- [Last.fm tracking and Spotify connection](https://www.last.fm/about/trackmymusic)
- [Dated history: user.getRecentTracks](https://www.last.fm/api/show/user.getRecentTracks)
- [Metadata and duration: track.getInfo](https://www.last.fm/api/show/track.getInfo)
- [Last.fm API terms, usage cap, and public-access conditions](https://www.last.fm/api/tos)
- [Similar artists: artist.getSimilar](https://www.last.fm/api/show/artist.getSimilar)
- [Community tags: artist.getTopTags](https://www.last.fm/api/show/artist.getTopTags)
- [Django overview](https://docs.djangoproject.com/en/5.2/intro/overview/)
- [Django supported releases](https://www.djangoproject.com/download/)
- [Chart.js](https://www.chartjs.org/docs/latest/)
- [Spotify developer policy](https://developer.spotify.com/policy)

Before milestone 1, inspect installed Python and settle reproducible dependencies. Before milestone 2, configure the Last.fm username and obtain an API key through Last.fm; never request secrets in chat. Before hosted/friend use, settle budget, access boundaries, profile verification, retention, and provider permissions.

The user authorized Milestone 1 and then prepared a Last.fm API key for Milestone 2. Work continues one milestone at a time through alternating pair programming. Milestone 3 is implemented; milestone 4 has not started.

## 9. Implementation progress

### Milestone 1: implemented and verified

- Environment: Python 3.12.12 in a project-local virtual environment; Django 5.2.19 with dependencies pinned in requirements.txt.
- Branch: milestone/01-local-dashboard. No commits or merges were created.
- Delivered: local dashboard, calendar-month form, two relative sample months, partial-month label, artist/track/album rankings, consistent invented totals, duration-coverage explanation, activity bars with a table equivalent, and empty/invalid states.
- All artist names, counts, and durations are synthetic. There are no external API calls, Last.fm credentials, external assets, or listening database models.
- Chart.js remains planned for milestone 4. The initial sample plot uses CSS bars so milestone 1 needs no JavaScript or frontend package setup.
- Verified: Django system checks, seven focused tests, dependency consistency, initial framework migrations, localhost responses/static assets, and headless Chrome desktop/mobile renders.
- Browser checks: no horizontal overflow at 1440px or 390px; month-form submission, older-month empty state, and return-to-current-month link work.
- Documentation: README.md contains Windows startup/recreation commands, request-to-template explanation, project map, verification commands, and a small learning exercise.
- Local database, virtual environment, browser profiles, and verification screenshots are ignored by Git.
- Next: review the local page and the learning exercise before implementing the read-only Last.fm client.

### Milestone 2: implemented and live connection verified

- Branch: milestone/02-lastfm-client. Earlier work and the user's template text change are preserved; no commits or merges were created.
- Added a read-only LastFmClient and RecordedPlay dataclass, plus the fetch_recent management command.
- Added optional --month filtering in Europe/Stockholm and --limit previews from 1 to 200 records.
- Pagination fixes the upper time bound, excludes now-playing entries, filters exact half-open time ranges, and bounds requests. Exact event duplicates across pages collapse.
- Errors are sanitized. Temporary service/network failures retry at most three times; invalid credentials and rate limits fail immediately. Responses and total page requests are bounded.
- Local .env is ignored by Git; .env.example contains only blank fields. Added python-dotenv 1.2.4, keeping existing environment variables authoritative.
- The user's initial configuration was entered into the example file. Values were moved into the ignored local file, and the example was restored to blank fields before final verification.
- Verified: Django checks; 27 offline tests, including all seven existing dashboard tests; live command returned three real recorded plays, with no API key in its output.
- This milestone is a terminal preview. Listening records are not persisted, and the browser dashboard still uses synthetic data.
- Next: the user can run fetch_recent to inspect real records; milestone 3 adds reliable storage and repeatable imports.

### Milestone 3: persistence and commands implemented

- The learner wrote duration parsing and tests for name normalization, duplicate-event rejection, and repeat-import behavior. Development switched to alternating small implementation pieces.
- Added models and an initial migration for listening profiles, tracks, timestamped listens, and sync attempts. The learner generated/applied the migration and made the storage-model commit.
- Added exact normalized identities and database uniqueness on profile, track, and timestamp. Separate later plays and different tracks at one timestamp remain valid.
- Added bounded page streaming for monthly history, atomic page saves/progress, safe retries, incomplete-window status, and an 80 MB SQLite/sidecar storage budget.
- Added bounded track-duration caching. Duration coverage is independent of import-window completion.
- Live verification imported 78 recorded plays; re-importing the same fixed window added zero and retained 78. One metadata lookup failed without invalidating history.
- Added sync_listening and show_listens, input/error handling, shared terminal sanitization, and command-level tests. Local reads require no API key or HTTP request.
- Local README contains command instructions, limits, and an intentional one-profile reset/reimport procedure. README and CONTRIBUTING remain locally excluded from Git.
- Before merging the milestone, run checks and review the feature-branch diff. Personal configuration and SQLite data remain ignored.
- Next: milestone 4 connects real database statistics to the dashboard through alternating implementation tasks.
