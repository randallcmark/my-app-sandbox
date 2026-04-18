from pathlib import Path

from app.auth.users import create_local_user
from app.core.config import settings
from app.db.models.artefact import Artefact
from app.db.models.job import Job
from app.db.models.job_artefact_link import JobArtefactLink
from app.main import app
from tests.test_local_auth_routes import build_client


def login(client, email: str, password: str = "password") -> None:
    response = client.post("/auth/login", json={"email": email, "password": password})

    assert response.status_code == 200


def test_artefact_library_requires_login(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)
    try:
        response = client.get("/artefacts")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_artefact_library_empty_state(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            create_local_user(db, email="jobseeker@example.com", password="password")
            db.commit()

        login(client, "jobseeker@example.com")

        response = client.get("/artefacts")

        assert response.status_code == 200
        assert "<h1>Artefacts</h1>" in response.text
        assert "No artefacts yet" in response.text
        assert 'href="/board"' in response.text
    finally:
        app.dependency_overrides.clear()


def test_artefact_library_lists_owned_job_artefacts(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            other_user = create_local_user(db, email="other@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Library role", company="Library Co")
            other_job = Job(owner_user_id=other_user.id, title="Other role", company="Other Co")
            db.add_all([job, other_job])
            db.flush()
            artefact = Artefact(
                owner_user_id=user.id,
                job_id=job.id,
                kind="resume",
                purpose="Tailored resume",
                version_label="v1",
                notes="Used for product roles.",
                filename="resume.txt",
                storage_key="jobs/library/artefacts/resume.txt",
                size_bytes=12,
            )
            other_artefact = Artefact(
                owner_user_id=other_user.id,
                job_id=other_job.id,
                kind="cover_letter",
                filename="other.txt",
                storage_key="jobs/other/artefacts/other.txt",
                size_bytes=10,
            )
            db.add_all([artefact, other_artefact])
            db.commit()
            job_uuid = job.uuid
            artefact_uuid = artefact.uuid

        login(client, "jobseeker@example.com")

        response = client.get("/artefacts")

        assert response.status_code == 200
        assert "resume.txt" in response.text
        assert "resume" in response.text
        assert "Tailored resume" in response.text
        assert "v1" in response.text
        assert "Used for product roles." in response.text
        assert "12 bytes" in response.text
        assert "Library role" in response.text
        assert "Library Co" in response.text
        assert f'href="/jobs/{job_uuid}"' in response.text
        assert f'href="/artefacts/{artefact_uuid}/download"' in response.text
        assert "other.txt" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_artefact_library_updates_metadata(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            other_user = create_local_user(db, email="other@example.com", password="password")
            db.flush()
            artefact = Artefact(
                owner_user_id=user.id,
                kind="resume",
                filename="resume.txt",
                storage_key="jobs/library/artefacts/resume.txt",
            )
            other_artefact = Artefact(
                owner_user_id=other_user.id,
                kind="resume",
                filename="hidden.txt",
                storage_key="jobs/hidden/artefacts/hidden.txt",
            )
            db.add_all([artefact, other_artefact])
            db.commit()
            artefact_id = artefact.id
            artefact_uuid = artefact.uuid
            other_artefact_uuid = other_artefact.uuid

        login(client, "jobseeker@example.com")

        response = client.post(
            f"/artefacts/{artefact_uuid}/metadata",
            data={
                "kind": "cover_letter",
                "purpose": "Narrative draft",
                "version_label": "v2",
                "notes": "Strong opener.",
                "outcome_context": "interview invite",
            },
            follow_redirects=False,
        )
        hidden_response = client.post(
            f"/artefacts/{other_artefact_uuid}/metadata",
            data={"kind": "cover_letter"},
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/artefacts"
        assert hidden_response.status_code == 404

        with session_local() as db:
            stored = db.get(Artefact, artefact_id)

            assert stored is not None
            assert stored.kind == "cover_letter"
            assert stored.purpose == "Narrative draft"
            assert stored.version_label == "v2"
            assert stored.notes == "Strong opener."
            assert stored.outcome_context == "interview invite"
    finally:
        app.dependency_overrides.clear()


def test_artefact_library_download_is_owner_scoped(tmp_path: Path, monkeypatch) -> None:
    artefact_root = tmp_path / "artefacts"
    monkeypatch.setattr(settings, "local_storage_path", str(artefact_root))
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            other_user = create_local_user(db, email="other@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Download role")
            other_job = Job(owner_user_id=other_user.id, title="Hidden role")
            db.add_all([job, other_job])
            db.flush()
            storage_key = "jobs/download/artefacts/resume.txt"
            other_storage_key = "jobs/hidden/artefacts/hidden.txt"
            (artefact_root / storage_key).parent.mkdir(parents=True)
            (artefact_root / storage_key).write_bytes(b"resume bytes")
            (artefact_root / other_storage_key).parent.mkdir(parents=True)
            (artefact_root / other_storage_key).write_bytes(b"hidden bytes")
            artefact = Artefact(
                owner_user_id=user.id,
                job_id=job.id,
                kind="resume",
                filename="resume.txt",
                storage_key=storage_key,
                content_type="text/plain",
                size_bytes=12,
            )
            other_artefact = Artefact(
                owner_user_id=other_user.id,
                job_id=other_job.id,
                kind="resume",
                filename="hidden.txt",
                storage_key=other_storage_key,
                content_type="text/plain",
                size_bytes=12,
            )
            db.add_all([artefact, other_artefact])
            db.commit()
            artefact_uuid = artefact.uuid
            other_artefact_uuid = other_artefact.uuid

        login(client, "jobseeker@example.com")

        response = client.get(f"/artefacts/{artefact_uuid}/download")
        hidden_response = client.get(f"/artefacts/{other_artefact_uuid}/download")

        assert response.status_code == 200
        assert response.content == b"resume bytes"
        assert response.headers["content-disposition"].endswith("resume.txt")
        assert hidden_response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_job_workspace_attaches_existing_artefact(tmp_path: Path, monkeypatch) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            other_user = create_local_user(db, email="other@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="Attach target")
            source_job = Job(owner_user_id=user.id, title="Source job")
            other_job = Job(owner_user_id=other_user.id, title="Hidden job")
            db.add_all([job, source_job, other_job])
            db.flush()
            artefact = Artefact(
                owner_user_id=user.id,
                job_id=source_job.id,
                kind="resume",
                filename="reuse.txt",
                storage_key="jobs/source/artefacts/reuse.txt",
            )
            other_artefact = Artefact(
                owner_user_id=other_user.id,
                job_id=other_job.id,
                kind="resume",
                filename="hidden.txt",
                storage_key="jobs/hidden/artefacts/hidden.txt",
            )
            db.add_all([artefact, other_artefact])
            db.commit()
            job_uuid = job.uuid
            artefact_uuid = artefact.uuid
            other_artefact_uuid = other_artefact.uuid

        login(client, "jobseeker@example.com")

        detail_response = client.get(f"/jobs/{job_uuid}")
        response = client.post(
            f"/jobs/{job_uuid}/artefact-links",
            data={"artefact_uuid": artefact_uuid},
            follow_redirects=False,
        )
        hidden_response = client.post(
            f"/jobs/{job_uuid}/artefact-links",
            data={"artefact_uuid": other_artefact_uuid},
        )

        assert detail_response.status_code == 200
        assert "reuse.txt" in detail_response.text
        assert response.status_code == 303
        assert response.headers["location"] == f"/jobs/{job_uuid}"
        assert hidden_response.status_code == 404

        with session_local() as db:
            links = db.query(JobArtefactLink).all()

            assert len(links) == 1
            assert links[0].job.title == "Attach target"
            assert links[0].artefact.filename == "reuse.txt"
    finally:
        app.dependency_overrides.clear()
