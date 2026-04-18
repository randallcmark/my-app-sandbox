# Job Detail

Job detail pages are available at:

```text
http://127.0.0.1:8000/jobs/job-uuid
```

The page requires a logged-in browser session and is owner-scoped. Another user's job returns
`404`.

New jobs can be created from:

```text
http://127.0.0.1:8000/jobs/new
```

## Current Behavior

- Presents the job as a workspace rather than a record form:
  - workspace header with title, company, location, salary, and stage pill;
  - next-action panel;
  - role overview;
  - readable job description;
  - application readiness checklist;
  - application and interview activity;
  - contextual aside for external links, state movement, artefacts, notes, and workflow actions.
- Shows captured provenance, including email capture details when available, in a collapsed
  details panel.
- Creates manual jobs from the browser.
- Edits job details after capture or manual creation by double-clicking displayed fields and saving
  inline changes through the jobs API.
- Shows the collapsed job journal, including `stage_change` events recorded from board movement.
- Displays journal timestamps in the browser's local timezone while keeping UTC as the stored
  server value and no-JavaScript fallback text.
- Changes workflow status explicitly from the detail page, including transitions between focused
  workflow views such as prospects, in-progress, outcomes, and archived.
- Adds notes to the timeline, with an optional follow-up date.
- Uploads, lists, and downloads job-level artefacts.
- Attaches an existing artefact to a job without copying the stored file.
- Links to the Artefact Library at `/artefacts` for a cross-job file view.
- Marks a job applied and creates or updates the application record.
- Schedules interviews and shows scheduled interview records.
- Archives a job with an optional timeline note.
- Restores an archived job to an active board status with an optional timeline note.
- Links back to Focus, Inbox, and Board.

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

3. Open the board:

```text
http://127.0.0.1:8000/board
```

4. Click a card title.

5. Confirm the detail page shows the workspace header, next action, role overview, description,
   readiness checklist, contextual aside, and collapsed journal.

6. Use Add job from the board, create a manual job, and confirm it opens the new detail page.

7. Double-click a displayed field such as title, status, location, URL, salary, or description.
   Change the value, click Save in the unsaved-changes bar, and confirm the corrected value remains
   after reload without clearing the other fields.

8. Upload a resume or cover letter artefact and confirm it appears in Artefacts with a download link.

9. Open another job workspace, attach the existing artefact, and confirm it appears there too.

10. Add a note with a follow-up date and confirm it appears in the timeline.

11. Use Mark Applied and confirm the page shows an application record and a timeline event.

12. Use Move status to move a job from a prospect state to an in-progress state, or from
    in-progress to an outcome state, and confirm the Journal records the stage change.

13. Schedule an interview and confirm the page shows an interview record and timeline event.

14. Use Archive and confirm the job is archived with a timeline event.

15. Open the archived job detail page, use Unarchive, choose an active status, and confirm the
   job returns to that status with a timeline event.

16. Move another job to a different stage on the board, then open the detail page again and expand
   Journal to confirm the new `stage_change` event appears.
