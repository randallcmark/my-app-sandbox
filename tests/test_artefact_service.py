import io
from pathlib import Path
import zipfile

from app.auth.users import create_local_user
from app.db.models.application import Application
from app.db.models.artefact import Artefact
from app.db.models.job import Job
from app.main import app
from app.services.artefacts import (
    list_candidate_artefacts_for_job,
    load_artefact_document_payload,
    load_artefact_text_excerpt,
    summarise_artefact_for_ai,
)
from tests.test_local_auth_routes import build_client


def test_list_candidate_artefacts_for_job_returns_owner_scoped_ranked_candidates(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            other_user = create_local_user(db, email="other@example.com", password="password")
            db.flush()

            current_job = Job(owner_user_id=user.id, title="Staff TPM", status="saved")
            prior_offer_job = Job(owner_user_id=user.id, title="Senior TPM", status="offer")
            prior_rejected_job = Job(owner_user_id=user.id, title="Operations Lead", status="rejected")
            other_job = Job(owner_user_id=other_user.id, title="Hidden role", status="offer")
            db.add_all([current_job, prior_offer_job, prior_rejected_job, other_job])
            db.flush()

            current_resume = Artefact(
                owner_user_id=user.id,
                job_id=current_job.id,
                kind="resume",
                purpose="TPM resume",
                version_label="v3",
                notes="Highlights platform delivery and cross-functional leadership.",
                filename="tpm-resume.pdf",
                storage_key="artefacts/tpm-resume.pdf",
            )
            successful_cover_letter = Artefact(
                owner_user_id=user.id,
                job_id=prior_offer_job.id,
                kind="cover_letter",
                purpose="Remote leadership cover letter",
                outcome_context="Used for offer stage process",
                filename="leadership-cover-letter.pdf",
                storage_key="artefacts/leadership-cover-letter.pdf",
            )
            weak_old_doc = Artefact(
                owner_user_id=user.id,
                job_id=prior_rejected_job.id,
                kind="other",
                filename="old-generic-doc.txt",
                storage_key="artefacts/old-generic-doc.txt",
            )
            hidden_other_user = Artefact(
                owner_user_id=other_user.id,
                job_id=other_job.id,
                kind="resume",
                filename="hidden-resume.pdf",
                storage_key="artefacts/hidden-resume.pdf",
            )
            db.add_all([current_resume, successful_cover_letter, weak_old_doc, hidden_other_user])
            db.commit()

            candidates = list_candidate_artefacts_for_job(db, user, current_job, limit=3)

        assert len(candidates) == 3
        assert candidates[0].filename == "tpm-resume.pdf"
        assert candidates[0].is_linked_to_current_job is True
        assert candidates[1].filename == "leadership-cover-letter.pdf"
        assert candidates[1].linked_offer_count == 1
        assert all(candidate.filename != "hidden-resume.pdf" for candidate in candidates)
        assert candidates[2].filename == "old-generic-doc.txt"
        assert candidates[0].score > candidates[1].score > candidates[2].score
    finally:
        app.dependency_overrides.clear()


def test_summarise_artefact_for_ai_includes_outcome_signals_and_related_context(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()

            current_job = Job(owner_user_id=user.id, title="Principal TPM", status="saved")
            interview_job = Job(owner_user_id=user.id, title="Platform Lead", status="interviewing")
            db.add_all([current_job, interview_job])
            db.flush()

            application = Application(
                owner_user_id=user.id,
                job_id=interview_job.id,
                status="submitted",
            )
            db.add(application)
            db.flush()

            artefact = Artefact(
                owner_user_id=user.id,
                application_id=application.id,
                kind="resume",
                purpose="Leadership-heavy resume",
                version_label="remote-v2",
                notes="Strong delivery and stakeholder management evidence.",
                outcome_context="Used in interview process",
                filename="leadership-resume.pdf",
                storage_key="artefacts/leadership-resume.pdf",
            )
            db.add(artefact)
            db.commit()
            db.refresh(artefact)

            summary = summarise_artefact_for_ai(artefact, current_job=current_job)

        assert summary.filename == "leadership-resume.pdf"
        assert summary.kind == "resume"
        assert summary.is_linked_to_current_job is False
        assert summary.linked_job_count == 1
        assert summary.linked_interview_count == 1
        assert summary.metadata_quality == "strong"
        assert "Purpose: Leadership-heavy resume" in summary.summary_text
        assert "Interview-linked jobs: 1" in summary.summary_text
        assert "Metadata quality: strong" in summary.summary_text
        assert "Already linked to current job: no" in summary.summary_text
        assert "Recent linked job titles: Platform Lead" in summary.summary_text
        assert "Notes: Strong delivery and stakeholder management evidence." in summary.summary_text
    finally:
        app.dependency_overrides.clear()


def test_list_candidate_artefacts_for_job_returns_empty_list_when_user_has_none(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            job = Job(owner_user_id=user.id, title="No artefacts role", status="saved")
            db.add(job)
            db.commit()

            candidates = list_candidate_artefacts_for_job(db, user, job)

        assert candidates == []
    finally:
        app.dependency_overrides.clear()


def test_summarise_artefact_for_ai_marks_thin_metadata_when_context_is_sparse(
    tmp_path: Path, monkeypatch
) -> None:
    client, session_local = build_client(tmp_path, monkeypatch)
    try:
        with session_local() as db:
            user = create_local_user(db, email="jobseeker@example.com", password="password")
            db.flush()
            current_job = Job(owner_user_id=user.id, title="Sparse role", status="saved")
            artefact = Artefact(
                owner_user_id=user.id,
                kind="other",
                filename="generic-doc.txt",
                storage_key="artefacts/generic-doc.txt",
            )
            db.add_all([current_job, artefact])
            db.commit()
            db.refresh(artefact)

            summary = summarise_artefact_for_ai(artefact, current_job=current_job)

        assert summary.metadata_quality == "thin"
        assert "Metadata quality: thin" in summary.summary_text
        assert "Missing metadata: purpose, version, notes, outcome context, linked history" in summary.summary_text
    finally:
        app.dependency_overrides.clear()


def test_load_artefact_text_excerpt_extracts_docx_text() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>Platform delivery</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>Stakeholder leadership</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
    artefact = Artefact(
        kind="resume",
        filename="baseline.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        storage_key="artefacts/baseline.docx",
    )

    excerpt = load_artefact_text_excerpt(
        artefact,
        storage=type("FakeStorage", (), {"load": lambda self, key: buffer.getvalue()})(),
    )

    assert excerpt is not None
    assert "Platform delivery" in excerpt
    assert "Stakeholder leadership" in excerpt


def test_load_artefact_text_excerpt_extracts_pdf_text_when_adapter_available(monkeypatch) -> None:
    artefact = Artefact(
        kind="resume",
        filename="baseline.pdf",
        content_type="application/pdf",
        storage_key="artefacts/baseline.pdf",
    )

    class FakeProvider:
        root = Path("/tmp/fake-root")

    monkeypatch.setattr("app.services.artefacts._local_storage_path", lambda artefact, provider: Path("/tmp/fake.pdf"))
    monkeypatch.setattr("app.services.artefacts._extract_pdf_text", lambda path: "Platform delivery from PDF")

    excerpt = load_artefact_text_excerpt(artefact, storage=FakeProvider())

    assert excerpt == "Platform delivery from PDF"


def test_load_artefact_document_payload_returns_pdf_bytes() -> None:
    artefact = Artefact(
        kind="resume",
        filename="baseline.pdf",
        content_type="application/pdf",
        storage_key="artefacts/baseline.pdf",
    )

    payload = load_artefact_document_payload(
        artefact,
        storage=type("FakeStorage", (), {"load": lambda self, key: b"%PDF-sample"})(),
    )

    assert payload == ("application/pdf", b"%PDF-sample")
