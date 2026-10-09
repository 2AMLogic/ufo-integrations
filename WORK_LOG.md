# Work Log

Merged pull requests and closed issues, grouped by date. Initial history covers the 30 days before this document was created.

### 2026-10-09

- **PR #165**: test: hold every skill to one frontmatter contract and resolve metadata.depends
- **PR #164**: test: hold each manifest's skills to the skill directories on disk
- **PR #163**: test: guard transition language across every extension tree
- **Issue #160** (closed): Pulse skills are not held to the Not-for rule, and no test resolves metadata.depends
- **Issue #159** (closed): Skill directories are never compared to the manifest, so an unlisted skill ships unchecked
- **Issue #158** (closed): The transition-language ban is enforced for matrix only, and pulse already breaks it

### 2026-10-07

- **PR #156**: chore: retire sweep-lease-fence resync pins (upstream #10027)
- **Issue #153** (closed): Retire the sweep-lease-fence.sh resync-ignore pins now that upstream #10027 covers old daemons

### 2026-10-01

- **PR #155**: chore: check the extensions with mypy in CI, at one pinned version
- **Issue #145** (closed): No mypy lane in CI, so a real structural-typing error shipped invisibly
- **Issue #43** (closed): uv.lock is untracked and unignored, so a documented test run dirties the tree

### 2026-09-30

- **PR #154**: fix(sweep-lease-fence): a daemon without 'forge check-branch' skips the leg rather than reporting a collision
- **PR #151**: fix: guard the delivered-row insert against a duplicate event
- **PR #150**: feat(matrix): declare homeserver topology, refuse shared-name collision
- **Issue #152** (closed): sweep-lease-fence.sh reports BRANCH_COLLISION on every issue: loom-daemon lacks 'forge check-branch' subcommand
- **Issue #124** (closed): write_delivered inserts without a conflict guard, so a duplicate would park the stream
- **Issue #115** (closed): The homeserver is one of three topologies, and vouching is written for one of them

### 2026-09-29

- **PR #149**: fix(matrix): a new device publishes one pool of one-time keys, not two
- **PR #148**: ci(ruff): one pinned ruff lane, holding every file to the 100-column wrap
- **PR #147**: ci: actionlint lane and compiled gate scripts
- **PR #146**: fix(lineage): the absent-parent fault names merge order as its resolution
- **PR #144**: fix: a store protocol asked for a settable workspace_id nothing provides
- **PR #143**: fix(matrix): an unlinkable write-up is said as a report, not as shared files
- **PR #142**: docs(pulse): coverage.py and the fall-through comment stop overclaiming
- **PR #141**: feat(pulse): the footer reads the coverage record through pulse_recall
- **Issue #140** (closed): pulse: two prose residues the #130 review found, both about the shell-write absolute
- **Issue #138** (closed): pulse: the coverage footer reads a projection that lands only in the last recording conversation
- **Issue #82** (closed): A new device publishes two pools of one-time keys on its first sync
- **Issue #64** (closed): No ruff lane in CI, and no [tool.ruff] config, so formatting drift is unenforced
- **Issue #58** (closed): No workflow linting in CI, so a malformed ci.yml reaches main unchecked
- **Issue #56** (closed): The absent-parent fault should name merge order as its resolution
- **Issue #53** (closed): A details artifact with no portal link tells the member it shared files

### 2026-09-28

- **PR #139**: test(pulse): the standing prompt's contract runs where no runtime is installed
- **PR #137**: feat(pulse): the coverage state is a table, and the gather records it with a tool
- **PR #136**: fix(matrix): a log field named status is the log's own level
- **PR #134**: fix(pulse-handoff): name AmbiguousSpawnTarget as the dominant bare-name failure
- **PR #132**: pulse: the agent's standing prompt names the record tools
- **PR #130**: pulse: two claims from #122/#128 that were not true, corrected
- **PR #129**: feat(pulse): a pulse runs as its own agent, and the gather it arms is that agent's
- **PR #128**: pulse: the scripts can no longer write, because prose did not stop them
- **PR #127**: pulse: the README census was wrong against its own argument, plus six smaller review items
- **PR #126**: pulse: a state line agrees in number with the count in front of it
- **PR #125**: ci(matrix): the homeserver job runs both gated modules, not one of them
- **PR #122**: pulse: one record per series, not one per carrier's working directory
- **PR #121**: fix(matrix): a replayed file event delivers the file it already delivered
- **PR #118**: docs(matrix): the homeserver's server_name decides the mode, not its URL
- **PR #116**: docs(matrix): the homeserver is one of three, and only one of them vouches
- **PR #114**: docs(matrix): the two things a correct-looking deploy still gets wrong
- **PR #113**: test(matrix): the media claims a fake cannot answer
- **PR #112**: test(matrix): the shared fakes hold the credential slots and what a tool said
- **PR #111**: feat(matrix): a file a member shares reaches the turn that answers them
- **PR #109**: feat(pulse): research runs daily, an edition is written when asked for
- **PR #108**: feat(pulse): a source's state per gather, so a window says how many days it failed
- **PR #107**: feat(pulse): the pool reads its own identities against each other
- **PR #106**: docs: the deploy note states its constraint, not its own lifespan
- **PR #105**: test(matrix): the reach test asserts the guard's walk, not a copy of it
- **PR #104**: feat(matrix): a member's file, fetched and opened before it is trusted
- **PR #102**: feat(matrix): a file a member sends is read as a file
- **PR #100**: fix(pulse): a sighting without a url is refused, not stored
- **PR #98**: fix(pulse): a failed write is part of the brief, not a detail to swallow
- **PR #97**: feat(matrix): an encrypted room takes sealed bytes, not only a sealed message
- **PR #93**: refactor(pulse): extract shared JSONL-store mechanics from seen.py and covered.py
- **PR #92**: fix(matrix): remove duplicate _said() helper from surface.py
- **PR #89**: test(matrix): the pack narrows the set the lockfile filled
- **PR #88**: docs: field-pulse falls back to asking when no business is found
- **PR #87**: docs(pulse): a running serve answers from the skills it booted with
- **PR #85**: fix(matrix): hold the SAS exchange bounds the table documents
- **PR #84**: docs(pulse): document armed-row staleness in field-pulse Traps
- **PR #81**: Encryption against a real homeserver, behind the same gate
- **PR #79**: A member verifies the bot's device over SAS
- **PR #77**: docs(matrix): why requires is empty, where the next reader looks
- **PR #76**: feat(matrix): the bytes an mxc names, fetched
- **PR #75**: feat(matrix): an EncryptedFile's bytes, sealed and opened
- **PR #74**: fix(pulse): a full-width slug in `seen fresh` no longer abuts its title
- **PR #72**: test(matrix): a wire version is an identifier, not transition language
- **PR #71**: feat(pulse): record what a gather saw, not only what an edition published
- **PR #69**: docs(matrix): the install path names the active set, not a store
- **PR #67**: docs(pulse): the pool's window, its idempotency, and the tests that guard its script
- **PR #65**: feat(pulse): a sightings pool, so collection is additive and staleness is a read
- **PR #63**: test(matrix): the one-seam guard reads every module but the transport
- **PR #62**: test: one distribution, two extensions, pinned and activated independently
- **PR #61**: feat(pulse): rank for the business owner, and let a quiet window be the answer
- **PR #60**: chore: Squad, so Claude and Codex share one room in this repo
- **PR #59**: docs(pulse): a turn with no carrier writes no ledger
- **PR #55**: fix: the lineage union reads every open pull request, not the first thirty
- **PR #50**: ci: catch a revision-id collision in the union of the open branches
- **PR #49**: docs: the root install path says what installing does and does not do
- **PR #45**: docs(pulse): the install path names the pack and the keys a deploy needs
- **PR #42**: fix: keep the covered ledger in the workspace the prose promises
- **PR #41**: docs: document OpenRouter-only boot-probe workaround in README
- **PR #33**: matrix: structured questions, live feedback, and addressed replies in group rooms
- **PR #32**: matrix: only lost fleet ownership ends a listener stream
- **PR #30**: feat: a turn answers its room in full — rich text, files, and mid-turn words
- **PR #29**: End-to-end encryption for the Matrix surface
- **Issue #133** (closed): pulse: the agent prompt's new paragraph over-claims the glob and the shell
- **Issue #131** (closed): pulse-handoff's bare-name trap names the wrong failure mode
- **Issue #123** (closed): coverage.py's store is still a workspace file, so a scheduled gather records no source states
- **Issue #120** (closed): pulse owns no store, so a scheduled fire builds no historical record
- **Issue #119** (closed): A crash-replayed batch now delivers a second numbered copy of the same file
- **Issue #117** (closed): A replayed file event is delivered twice, though the message it came on is admitted once
- **Issue #110** (closed): pulse: coverage.py's state_line writes "1 items" and "nothing in them" for a single gather
- **Issue #103** (closed): pulse should be its own agent, and a scheduled row cannot name one
- **Issue #95** (closed): A scheduled pulse fire records nothing and does not report it
- **Issue #94** (closed): Remove duplicate test fakes: Credentials and said() repeated across matrix test files
- **Issue #91** (closed): pulse: replace field-pulse's fused scheduled task with a daily gather + on-demand report
- **Issue #90** (closed): pulse: record per-source coverage state per gather, so coverage-honesty can aggregate a multi-day window
- **Issue #86** (closed): Remove duplicated JSONL store mechanics: brief-continuity's seen.py and covered.py
- **Issue #83** (closed): Remove duplicate _said() helper: identical in surface.py and linking.py
- **Issue #80** (closed): The SAS exchange table's bounds are looser than it documents
- **Issue #73** (closed): The seam guard's reach test walks its own duplicate, so narrowing the guard passes green
- **Issue #70** (closed): A running serve keeps the skills it booted with, so a skill edit does not reach it
- **Issue #68** (closed): The transition-language guard rejects the EncryptedFile wire version, so #46 cannot be written
- **Issue #66** (closed): An armed scheduled row keeps the prompt it was created with, so a skill edit never reaches it
- **Issue #57** (closed): The one-seam guard reads surface.py alone, so a bypass elsewhere is uncaught
- **Issue #54** (closed): Deploy notes narrate their own removal rather than describing the constraint
- **Issue #52** (closed): pulse: rank for the business owner, not for someone working in the field
- **Issue #51** (closed): pulse: split daily gathering from on-demand reporting
- **Issue #48** (closed): Encryption against a real homeserver, behind a marker
- **Issue #47** (closed): Verifying the bot's Matrix device beyond trust on first use
- **Issue #46** (closed): Encrypted attachments: EncryptedFile media in a Matrix room
- **Issue #44** (closed): pulse: document client-driven runs (file capability) + init default-set trap in the README
- **Issue #40** (closed): memory_search unavailable without an OpenAI embeddings key, so field-pulse step 1 silently cannot run
- **Issue #39** (closed): pulse README's install path yields a deploy where pulse never activates (ufoctl init pins [pack] assistant)
- **Issue #38** (closed): pulse: derive the field from the active business, and say what happens when there is none
- **Issue #37** (closed): pulse: brief-continuity prose says the covered ledger is a workspace file; covered.py keeps it at $UFO_HOME/pulse
- **Issue #36** (closed): A skill trap's mechanism needs a registry-side test, not only its tells
- **Issue #35** (closed): CI cannot see a migration revision-id collision between two open branches
- **Issue #34** (closed): deploy: ufoctl serve cannot boot with only an OpenRouter model key (egress probe ignores OPENROUTER_API_KEY)
- **Issue #23** (closed): matrix: narrow Installation.run's RuntimeError pass-through to a typed ownership-loss error
- **Issue #18** (closed): matrix: live end-to-end — ufo answers in a real Matrix room
- **Issue #16** (closed): matrix: end-to-end encryption (Olm/Megolm, persistent device, encrypted media)
- **Issue #14** (closed): pulse: end-to-end smoke run against a real ufoctl serve
- **Issue #8** (closed): matrix: ask_user rendering, typing feedback, ambient replies in group rooms
- **Issue #7** (closed): matrix: durable delivery via post/attach/speak
- **Issue #1** (closed): Matrix chat surface (tracking)

### 2026-09-27

- **PR #31**: fix(matrix): bare deploy key core prefixes, and README traps for foreign permanence and pre-join backfill
- **PR #28**: fix: a lost database is read again rather than skipped
- **PR #27**: matrix: members link their MXID by proof
- **PR #26**: matrix: connect a workspace in chat, as an action on the surface row
- **PR #21**: matrix: a durable chat surface, rooms as conversations
- **PR #20**: test: gate extensions on upstream's import boundaries
- **PR #19**: ci: the registry job fails when the registry test skips, and runs nightly
- **Issue #25** (closed): matrix: deploy_keys declares UFO_MATRIX_BOTS, so init reports UFO_UFO_MATRIX_BOTS
- **Issue #24** (closed): matrix: document that foreign rooms stay foreign, and pre-join backfill
- **Issue #22** (closed): matrix: members link their MXID by proof (public homeservers)
- **Issue #17** (closed): Register a dedicated Matrix bot account for ufo
- **Issue #15** (closed): matrix: a durable chat surface — rooms as conversations, unencrypted v1
- **Issue #13** (closed): Verify one distribution with two extensions pins and activates each independently
- **Issue #12** (closed): Gate: extensions import only ufo.sdk; skill scripts import nothing from ufo
- **Issue #11** (closed): CI: run the registry test against ufo@main, and nightly
- **Issue #10** (closed): matrix: upstream any ufo.sdk gaps instead of forking (listener cursor is one int per surface)
- **Issue #9** (closed): matrix: decide end-to-end encrypted room support
- **Issue #6** (closed): matrix: /sync listener admits room messages as turns
- **Issue #5** (closed): matrix: map MXIDs to members and rooms to conversation audiences
- **Issue #4** (closed): matrix: connect a workspace in chat (credential slots, bind_installation)
- **Issue #3** (closed): matrix: decide transport (/sync listener vs Application Service) and tenancy
- **Issue #2** (closed): matrix: scaffold the extension package and contract tests
