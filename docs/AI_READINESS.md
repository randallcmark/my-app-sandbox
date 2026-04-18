# AI Readiness

AI support is intentionally split into two parts:

- durable, visible records that can be reviewed by the user;
- future provider execution that may create those records.

This slice implements the durable records and provider placeholders only. It does not store API
keys, call external providers, mutate jobs, mutate profiles, or change workflow state.

## Provider Placeholders

Open Settings:

```text
http://127.0.0.1:8000/settings#ai
```

Supported placeholder providers:

- OpenAI;
- Anthropic;
- OpenAI-compatible local endpoint.

Fields:

- provider;
- label;
- base URL;
- model name;
- enabled flag.

The enabled flag is only configuration metadata in this slice. It does not trigger any external
request.

## AI Output Records

The database can now store visible AI output records for:

- recommendation;
- fit summary;
- draft;
- profile observation;
- artefact suggestion.

Each output is owner-scoped and may be tied to a job, artefact, provider, model, and source context.
Future UI work should render these records where the user is working, such as the job workspace,
Inbox, Focus, or Artefact Library.

## Contract

- AI is optional.
- AI output is inspectable.
- AI never silently changes jobs, artefacts, profile data, or workflow state.
- External calls must not happen unless a provider is explicitly configured in a future execution
  slice.
