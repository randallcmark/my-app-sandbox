# User Profile And Intent

The user profile records what the jobseeker is trying to achieve. It is the foundation for the planned Focus, Inbox, search, and optional AI guidance surfaces.

The first version is manual and owner-scoped. It does not call AI services and it does not change workflow state.

## Browser UI

Open User Settings from the username menu and use the Job-search profile section:

```text
http://127.0.0.1:8000/settings#profile
```

The profile captures:

- target roles;
- target locations;
- remote preference;
- salary minimum, maximum, and currency;
- preferred industries;
- industries to avoid;
- constraints;
- urgency;
- positioning notes.

Use multi-line fields for lists or rough notes. The app stores the text as entered so future features can interpret it without forcing a premature taxonomy.

## API

Read the current user's profile:

```bash
curl -s \
  -b cookies.txt \
  http://127.0.0.1:8000/api/profile
```

Create or replace the current user's profile:

```bash
curl -s -X PUT \
  -b cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{
    "target_roles": "Engineering Manager\nProduct Engineering Lead",
    "target_locations": "London\nRemote",
    "remote_preference": "hybrid",
    "salary_min": "90000",
    "salary_max": "125000",
    "salary_currency": "GBP",
    "preferred_industries": "Developer tools\nAI infrastructure",
    "excluded_industries": "Gambling",
    "constraints": "No full-time office work.",
    "urgency": "actively searching",
    "positioning_notes": "Hands-on technical leader."
  }' \
  http://127.0.0.1:8000/api/profile
```

Authentication uses the normal browser session. API token support for profile management is intentionally not part of the first slice.

## Roadmap Role

Phase 2 Focus should use this profile to tailor empty states and prioritisation language.

Phase 3 Inbox should use this profile when explaining why an imported or recommended job deserves review.

Phase 6 AI readiness should use this profile as source context for visible recommendations, fit summaries, drafts, profile observations, and artefact suggestions.
