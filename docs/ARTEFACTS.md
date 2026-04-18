# Artefacts

Artefacts are files used during a job search: resumes, cover letters, application notes,
interview prep, attestations, and other reusable working materials.

The first library surface is available at:

```text
http://127.0.0.1:8000/artefacts
```

The page requires a logged-in browser session and is owner-scoped.

## Current Behavior

- Lists all artefacts owned by the logged-in user.
- Shows filename, kind, purpose, version label, notes, size, updated timestamp, and linked jobs.
- Edits artefact metadata from the library:
  - kind;
  - purpose;
  - version label;
  - outcome context;
  - notes.
- Links back to associated job workspaces.
- Attaches an existing artefact to another job from that job workspace without copying the file.
- Provides an owner-scoped download path:

```text
http://127.0.0.1:8000/artefacts/artefact-uuid/download
```

- Keeps existing job-level upload and download behavior intact.

## Current Limitations

- Upload still happens from a job workspace.
- Reuse is intentionally simple: one stored file can be linked to multiple jobs, but application
  and interview-level reuse flows are not exposed yet.
- Text extraction, semantic search, and AI suggestions are not implemented yet.

## Browser Test

1. Start the app:

```bash
source .venv/bin/activate
make run
```

2. Sign in at:

```text
http://127.0.0.1:8000/login
```

3. Open any job workspace:

```text
http://127.0.0.1:8000/board
```

4. Upload an artefact from the job workspace.

5. Open:

```text
http://127.0.0.1:8000/artefacts
```

6. Confirm the artefact appears with its linked job and download action.

7. Expand Edit metadata, add purpose, version, notes, and outcome context, then save.

8. Download the artefact from the library and confirm it matches the uploaded file.

9. Open a different job workspace, use Attach Existing, and confirm the same artefact appears on
   that job without uploading it again.
