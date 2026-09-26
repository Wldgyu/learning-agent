"""Verified image transcriptions belong to the local study database."""
import hashlib


def context_fingerprint(question) -> str:
    material = question["question_text"] + "\n" + question["image_urls"]
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def verified_image_text(db, question) -> str:
    row = db.execute(
        "SELECT transcription, fingerprint FROM question_context WHERE question_id=?",
        (question["id"],),
    ).fetchone()
    if row and row["fingerprint"] == context_fingerprint(question):
        return row["transcription"]
    return ""
