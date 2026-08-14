# Native Codex Agent Communication

Danus uses native Codex thread messages for live agent-to-agent coordination
when the Codex app thread tools are available. Durable Danus stores remain the
authority for proof state.

## Channel map

| Sender | Receiver | Primary channel | Durable authority |
| --- | --- | --- | --- |
| proof main | engineering supervisor | native Codex thread message | recovery log only |
| engineering supervisor | proof main | native Codex thread message | recovery log only |
| proof main | strategy consultant | native Codex thread message containing the published elaboration | `global_memory/elaboration.jsonl` |
| strategy consultant | proof main | native Codex thread message containing the complete reply | `global_memory/master_guidance.jsonl` after `gm_add` |
| proof main | worker | `danus assign`, which writes the worker's `TASK.md` | `TASK.md` |
| worker | proof main and peers | `gm_add` and `fact_submit` | global memory and the verifier-backed fact graph |

Direct messages are an operational transport, not a proof store. A mathematical
claim in a message is not verified and must not be cited as a fact until a worker
submits it and the verifier accepts it.

## Thread registry

The active project may keep ephemeral thread addresses in
`runtime/projects/<project>/main-agent/thread-routing.json`. The registry stores
identifiers and roles only; it must not copy consultation, engineering, or proof
payloads. `runtime/` is gitignored because thread identifiers are deployment
state rather than repository configuration.

## Engineering request protocol

1. The proof main sends one compact message to the engineering supervisor with
   a request ID, the blocked step, exact command or tool, exact error, affected
   surface, and smallest requested engineering action.
2. The proof main pauses only the affected engineering-dependent step. It keeps
   independent verification, monitoring, or worker work running when safe.
3. The supervisor replies to the proof-main thread with the disposition and the
   exact recovery action.
4. If native delivery fails, append the same request to
   `ENGINEERING-QUESTIONS.md` or the answer to `ENGINEERING-ANSWERS.md`, including
   the native-delivery error. These files are recovery mailboxes, not queues to
   poll during normal operation.

## Consultation protocol

1. The proof main prepares a fresh elaboration from shared global memory and the
   fact graph, then publishes it with `gm_add(kind="elaboration", ...)`.
2. It creates or reuses a dedicated consultant thread configured as
   `gpt-5.6-sol` with `max` reasoning effort and sends the complete elaboration
   by native Codex message. The prompt includes the proof-main callback thread.
3. The consultant returns the complete strategy reply to the proof-main thread.
   The consultant must not edit project state or describe advice as verified.
4. The proof main records the reply verbatim with
   `gm_add(kind="master_guidance", ...)`, linked to the elaboration, before it
   dispatches workers. Native thread APIs do not expose metered usage, so this
   route records zero token/cost fields and notes that it consumes ChatGPT quota.
5. If native thread tools are unavailable or delivery fails, use the repository
   wrapper from the checkout root:

   ```bash
   ./bin/consult --file <elaboration.md> --project <project_dir> --out <reply.md>
   ```

   The CLI route retains its normal spend ledger and response envelope.

## Worker communication decision

Workers remain managed `codex exec` processes. Their stable interfaces are
assignments, shared findings, and verifier submissions, so worker-to-main traffic
continues through Danus rather than app-thread messages. This preserves restart
recovery, deduplication, and verifier gating. If workers later become native
Codex threads, direct messages may be added for liveness and clarification, but
`TASK.md`, global memory, and the fact graph must remain authoritative.

## Failure rules

- A missing native-message capability falls back to the durable mailbox or CLI;
  it does not silently drop the payload.
- A missing bare `consult` command is not blocking when `./bin/consult` or a
  native consultant thread is available.
- A consultant failure does not create empty `master_guidance`.
- A messaging failure never authorizes hand-editing global memory or the fact
  graph.
