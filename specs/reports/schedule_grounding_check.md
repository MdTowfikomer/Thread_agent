# Schedule grounding check — 2026-10-29

The user observed a web answer incorrectly treating an Aurora review on Monday
at 11 AM and an Aurora demo on Friday at 3 PM as conflicting schedules. A subsequent
Slack answer correctly answered the review question from Telegram evidence.

## Change

Both streaming prompt preparation and synchronous synthesis now share the same
evidence reasoning instructions: identify the exact subject, event occurrence and
attribute before considering conflict. Different events within a project may have
different schedules. Record timestamps do not establish event identity or event
dates. Genuine incompatible same-event claims still require an explicit supported
update or acknowledgement of uncertainty.

## Verification

Used synthetic citations with the active workspace's `gemini-3.5-flash-lite`
connection through the real prompt builder and scoped model invocation. No platform
messages, organizational source records or new chat turns were created by the check.

- Before the change, an isolated review-versus-demo sample answered correctly.
  Thus the original reported failure was not deterministically reproduced by that
  sample, and these checks do not establish an LLM correctness guarantee.
- After the change, review versus demo answered Monday at 11 AM, without a false
  schedule conflict.
- After the change, two incompatible times for the same Aurora review were
  explicitly identified as an unresolved conflict.
- Existing source-injection security test: one passed; PostgreSQL variant skipped
  because no disposable test database was configured.
- `git diff --check` passed for the changed workflow file.

The user's Slack response independently verifies that Telegram evidence can be
retrieved and cited in a Slack answer for the Novaflow workspace.
