"""Verified image transcriptions belong to the local study database."""
import hashlib
import json


def context_fingerprint(question) -> str:
    material = question["question_text"] + "\n" + question["image_urls"]
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def verified_image_text(db, question) -> str:
    row = db.execute(
        "SELECT transcription, fingerprint FROM question_context WHERE question_id=?",
        (question["id"],),
    ).fetchone()
    if row and row["fingerprint"] == context_fingerprint(question):
        return row["transcription"].strip()
    return ""


def save_verified_image_text(db, question, transcription: str) -> None:
    """Save only text that has been checked against every image in the question."""
    if not transcription.strip() or not json.loads(question["image_urls"]):
        raise ValueError("이미지와 확인한 설명 내용이 모두 필요합니다.")
    db.execute(
        """INSERT INTO question_context(question_id, fingerprint, transcription) VALUES(?,?,?)
           ON CONFLICT(question_id) DO UPDATE SET
           fingerprint=excluded.fingerprint, transcription=excluded.transcription""",
        (question["id"], context_fingerprint(question), transcription.strip()),
    )


def audit_image_contexts(db) -> dict:
    rows = db.execute("SELECT * FROM question ORDER BY year, round, number").fetchall()
    image_questions = 0
    image_count = 0
    pending = []
    for question in rows:
        urls = json.loads(question["image_urls"])
        if not urls:
            continue
        image_questions += 1
        image_count += len(urls)
        if not verified_image_text(db, question):
            pending.append({"id": question["id"], "year": question["year"],
                            "round": question["round"], "number": question["number"]})
    return {"total_questions": len(rows), "image_questions": image_questions,
            "image_count": image_count, "ready_questions": image_questions - len(pending),
            "pending_questions": pending}


if __name__ == "__main__":
    from .db import connect

    with connect() as connection:
        print(json.dumps(audit_image_contexts(connection), ensure_ascii=False, indent=2))
