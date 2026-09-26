from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import llm_service
from .db import connect, initialize
from .services import build_plan, complete_attempt, grade, now, suggested_difficulty
from .text_format import format_answer
from .question_context import verified_image_text


ROOT = Path(__file__).resolve().parent.parent
initialize()
app = FastAPI(title="AI 학습 Agent", version="0.1.0")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/assets", StaticFiles(directory=ROOT / "source_cache" / "images", check_dir=False), name="assets")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self'; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def record(row):
    return dict(row) if row is not None else None


def ai_http_error(exc: RuntimeError) -> HTTPException:
    return HTTPException(503 if isinstance(exc, llm_service.ServiceUnavailableError) else 502, str(exc))


def ai_text(value) -> str:
    """Turn varying AI JSON field shapes into readable SQLite text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := ai_text(item)))
    if isinstance(value, dict):
        return "\n".join(f"{key}: {part}" for key, item in value.items()
                         if (part := ai_text(item)))
    return str(value)


def require_question(db, question_id: int):
    row = db.execute("""SELECT q.*,m.category,m.subcategory,m.difficulty
                        FROM question q JOIN question_meta m ON m.question_id=q.id WHERE q.id=?""",
                     (question_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "문제를 찾을 수 없습니다.")
    return row


class AnswerIn(BaseModel):
    question_id: int | None = None
    generated_question_id: int | None = None
    user_answer: str = Field(min_length=1, max_length=5000)
    elapsed_seconds: int = Field(default=0, ge=0, le=86400)
    mode: str = Field(default="source", max_length=32)


class ReviewIn(BaseModel):
    is_correct: bool


class GenerateIn(BaseModel):
    source_question_id: int | None = None
    category: str | None = Field(default=None, max_length=100)
    subcategory: str | None = Field(default=None, max_length=100)
    mode: str = Field(default="similar", max_length=20)


class TheoryIn(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    subcategory: str = Field(min_length=1, max_length=100)


class ExamAnswer(BaseModel):
    question_id: int
    user_answer: str = Field(default="", max_length=5000)


class ExamSubmission(BaseModel):
    answers: list[ExamAnswer] = Field(min_length=20, max_length=20)
    elapsed_seconds: int = Field(default=0, ge=0, le=86400)


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/status")
def status():
    with connect() as db:
        return {"questions": db.execute("SELECT COUNT(*) FROM question").fetchone()[0],
                "rounds": db.execute("SELECT COUNT(*) FROM source_page").fetchone()[0],
                "ai_enabled": llm_service.available()}


@app.get("/api/questions")
def list_questions(year: int | None = None, round: int | None = None,
                   category: str | None = None, search: str | None = None,
                   page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
    clauses = ["1=1"]
    params: list = []
    if year is not None:
        clauses.append("q.year=?"); params.append(year)
    if round is not None:
        clauses.append("q.round=?"); params.append(round)
    if category:
        clauses.append("m.category=?"); params.append(category)
    if search:
        clauses.append("q.question_text LIKE ?"); params.append("%" + search[:100] + "%")
    where = " AND ".join(clauses)
    with connect() as db:
        total = db.execute(f"SELECT COUNT(*) FROM question q JOIN question_meta m ON q.id=m.question_id WHERE {where}", params).fetchone()[0]
        rows = db.execute(f"""SELECT q.id,q.year,q.round,q.number,substr(q.question_text,1,150) AS preview,
                              q.review_flags,m.category,m.subcategory,m.difficulty
                              FROM question q JOIN question_meta m ON q.id=m.question_id
                              WHERE {where} ORDER BY q.year DESC,q.round DESC,q.number
                              LIMIT ? OFFSET ?""", params + [size, (page - 1) * size]).fetchall()
        return {"total": total, "page": page, "items": [record(row) for row in rows]}


@app.get("/api/questions/{question_id}")
def get_question(question_id: int):
    with connect() as db:
        row = require_question(db, question_id)
        result = {key: row[key] for key in ("id", "year", "round", "number", "question_text",
                                              "review_flags", "category", "subcategory", "difficulty")}
        manifest_path = ROOT / "source_cache" / "image_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        result["local_images"] = ["/assets/" + manifest[url] for url in json.loads(row["image_urls"]) if url in manifest]
        return result


@app.get("/api/generated/{generated_id}")
def get_generated(generated_id: int):
    with connect() as db:
        row = db.execute("""SELECT id,question_text,category,subcategory,difficulty,mode FROM generated_question
                            WHERE id=? AND user_id=1 AND validation_status='valid'""", (generated_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "생성 문제를 찾을 수 없습니다.")
        return record(row)


@app.get("/api/generated")
def list_generated(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
    with connect() as db:
        total = db.execute("""SELECT COUNT(*) FROM generated_question
                              WHERE user_id=1 AND validation_status='valid'""").fetchone()[0]
        rows = db.execute("""SELECT id,substr(question_text,1,150) AS preview,
                             category,subcategory,difficulty,mode,created_at
                             FROM generated_question
                             WHERE user_id=1 AND validation_status='valid'
                             ORDER BY id DESC LIMIT ? OFFSET ?""",
                          (size, (page - 1) * size)).fetchall()
        return {"total": total, "page": page, "items": [record(row) for row in rows]}


@app.get("/api/exams")
def list_exams():
    with connect() as db:
        return {"items": [record(row) for row in db.execute("""SELECT year,round,question_count
                           FROM source_page ORDER BY year DESC,round DESC""")]}


@app.get("/api/exams/{year}/{round_number}")
def get_exam(year: int, round_number: int):
    with connect() as db:
        rows = db.execute("""SELECT q.id,q.number,q.question_text,q.image_urls,m.category,m.subcategory
                             FROM question q JOIN question_meta m ON m.question_id=q.id
                             WHERE q.year=? AND q.round=? ORDER BY q.number""",
                          (year, round_number)).fetchall()
    if len(rows) != 20:
        raise HTTPException(404, "해당 회차의 20문항을 찾을 수 없습니다.")
    manifest_path = ROOT / "source_cache" / "image_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    items = []
    for row in rows:
        item = {key: row[key] for key in ("id", "number", "question_text", "category", "subcategory")}
        item["local_images"] = ["/assets/" + manifest[url] for url in json.loads(row["image_urls"]) if url in manifest]
        items.append(item)
    return {"year": year, "round": round_number, "items": items}


@app.post("/api/exams/{year}/{round_number}/submit")
def submit_exam(year: int, round_number: int, payload: ExamSubmission):
    with connect() as db:
        rows = db.execute("SELECT id,number,answer,answer_html FROM question WHERE year=? AND round=? ORDER BY number",
                          (year, round_number)).fetchall()
        answer_map = {answer.question_id: answer.user_answer.strip() for answer in payload.answers}
        if len(rows) != 20 or len(answer_map) != 20 or set(answer_map) != {row["id"] for row in rows}:
            raise HTTPException(400, "이 회차의 20문항 답안을 모두 보내야 합니다.")
        results = []
        for row in rows:
            user_answer = answer_map[row["id"]]
            is_correct, method = grade(user_answer, row["answer"]) if user_answer else (False, "blank")
            cursor = db.execute("""INSERT INTO attempt(question_id,user_answer,correct_answer,grading_method,
                                  elapsed_seconds,mode) VALUES(?,?,?,?,?,?)""",
                                (row["id"], user_answer, row["answer"], method,
                                 payload.elapsed_seconds, f"exam:{year}-{round_number}"))
            if is_correct is not None:
                complete_attempt(db, cursor.lastrowid, is_correct)
            results.append({"number": row["number"], "question_id": row["id"], "attempt_id": cursor.lastrowid,
                            "user_answer": user_answer, "correct_answer": format_answer(row["answer_html"], row["answer"]),
                            "is_correct": is_correct, "grading_method": method})
        return {"year": year, "round": round_number, "results": results,
                "correct": sum(result["is_correct"] is True for result in results),
                "pending": sum(result["is_correct"] is None for result in results)}


@app.post("/api/attempts")
def submit_answer(payload: AnswerIn):
    if bool(payload.question_id) == bool(payload.generated_question_id):
        raise HTTPException(400, "문제 ID 하나만 지정하세요.")
    with connect() as db:
        if payload.question_id:
            question = require_question(db, payload.question_id)
            correct_answer = question["answer"]
        else:
            question = db.execute("SELECT * FROM generated_question WHERE id=? AND user_id=1 AND validation_status='valid'",
                                  (payload.generated_question_id,)).fetchone()
            if question is None:
                raise HTTPException(404, "생성 문제를 찾을 수 없습니다.")
            correct_answer = question["answer"]
        auto_result, method = grade(payload.user_answer, correct_answer)
        cursor = db.execute("""INSERT INTO attempt(question_id,generated_question_id,user_answer,correct_answer,
                              grading_method,elapsed_seconds,mode) VALUES(?,?,?,?,?,?,?)""",
                            (payload.question_id, payload.generated_question_id, payload.user_answer.strip(),
                             correct_answer, method, payload.elapsed_seconds, payload.mode))
        result = None
        if auto_result is not None:
            result = complete_attempt(db, cursor.lastrowid, auto_result)
        display_answer = format_answer(question["answer_html"], correct_answer) if payload.question_id else correct_answer
        return {"attempt_id": cursor.lastrowid, "correct_answer": display_answer,
                "grading_method": method, "result": result,
                "explanation": question["explanation"] if payload.generated_question_id else None}


@app.post("/api/attempts/{attempt_id}/review")
def review_answer(attempt_id: int, payload: ReviewIn):
    with connect() as db:
        try:
            return complete_attempt(db, attempt_id, payload.is_correct)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc


@app.post("/api/attempts/{attempt_id}/analyze")
def analyze_attempt(attempt_id: int):
    with connect() as db:
        attempt = db.execute("SELECT * FROM attempt WHERE id=?", (attempt_id,)).fetchone()
        if attempt is None or attempt["is_correct"] != 0:
            raise HTTPException(400, "채점이 끝난 오답만 분석할 수 있습니다.")
        if attempt["question_id"]:
            question = require_question(db, attempt["question_id"])
        else:
            question = db.execute("SELECT * FROM generated_question WHERE id=?", (attempt["generated_question_id"],)).fetchone()
        if not llm_service.available():
            raise HTTPException(503, ".env에 API 키를 입력하세요.")
        image_context = verified_image_text(db, question) if attempt["question_id"] else ""
        missing_images = bool(attempt["question_id"] and json.loads(question["image_urls"]) and not image_context)
        try:
            analysis = llm_service.analyze_wrong(question["question_text"], attempt["correct_answer"],
                                                  attempt["user_answer"], question["category"], question["subcategory"],
                                                  image_context=image_context, missing_image_context=missing_images)
        except RuntimeError as exc:
            raise ai_http_error(exc) from exc
        if not isinstance(analysis, dict):
            raise HTTPException(502, "AI 분석 응답 형식이 올바르지 않습니다.")
        concepts = analysis.get("weak_concepts")
        steps = analysis.get("steps")
        analysis = {"cause": ai_text(analysis.get("cause")),
                    "feedback": ai_text(analysis.get("feedback")),
                    "steps": [ai_text(item) for item in steps] if isinstance(steps, list) else [],
                    "next_tip": ai_text(analysis.get("next_tip")),
                    "weak_concepts": [ai_text(item) for item in concepts] if isinstance(concepts, list) else []}
        if missing_images:
            return analysis
        id_column = "question_id" if attempt["question_id"] else "generated_question_id"
        db.execute(f"""UPDATE wrong_answer SET wrong_reason=?,weak_concept=? WHERE user_id=1 AND {id_column}=?""",
                   (analysis["cause"], json.dumps(analysis["weak_concepts"], ensure_ascii=False),
                    attempt["question_id"] or attempt["generated_question_id"]))
        return analysis


@app.post("/api/generated")
def generate(payload: GenerateIn):
    if not llm_service.available():
        raise HTTPException(503, ".env에 API 키를 입력하세요.")
    if payload.mode not in {"similar", "expected"}:
        raise HTTPException(400, "mode는 similar 또는 expected여야 합니다.")
    with connect() as db:
        source = require_question(db, payload.source_question_id) if payload.source_question_id else None
        category = payload.category or (source["category"] if source else None)
        subcategory = payload.subcategory or (source["subcategory"] if source else None)
        if not category or not subcategory:
            raise HTTPException(400, "분야와 세부 개념을 지정하세요.")
        count = 5 if payload.mode == "similar" else 10
        references = db.execute("""SELECT q.question_text,q.answer FROM question q JOIN question_meta m ON m.question_id=q.id
                                  WHERE m.category=? AND m.subcategory=? ORDER BY q.year DESC,q.round DESC LIMIT ?""",
                                (category, subcategory, count)).fetchall()
        if len(references) < 3:
            raise HTTPException(400, "참고 문제가 3개 이상 필요합니다.")
        difficulty = suggested_difficulty(db)
        try:
            candidate = llm_service.generate_question(
                [{"question": row["question_text"][:1800], "answer": row["answer"][:300]} for row in references],
                category, subcategory, difficulty, payload.mode)
            if not isinstance(candidate, dict):
                raise RuntimeError("AI 문제 응답 형식이 올바르지 않습니다.")
            question_text = ai_text(candidate.get("question_text"))
            answer = ai_text(candidate.get("answer"))
            explanation = ai_text(candidate.get("explanation"))
            if not question_text or not answer:
                raise RuntimeError("생성 결과에 문제나 답이 없습니다.")
            concepts = candidate.get("concepts")
            candidate = {"question_text": question_text, "answer": answer,
                         "explanation": explanation,
                         "concepts": [ai_text(item) for item in concepts] if isinstance(concepts, list) else []}
            verdict = llm_service.validate_question(candidate, category, subcategory)
            if not isinstance(verdict, dict):
                raise RuntimeError("AI 검증 응답 형식이 올바르지 않습니다.")
        except RuntimeError as exc:
            raise ai_http_error(exc) from exc
        issues = verdict.get("issues")
        issues = [ai_text(item) for item in issues] if isinstance(issues, list) else []
        valid = verdict.get("valid") is True and verdict.get("answer_correct") is True and verdict.get("ambiguity") is False
        cursor = db.execute("""INSERT INTO generated_question(source_question_id,question_text,answer,explanation,
                              difficulty,category,subcategory,concepts,validation_status,validation_issues,mode)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (payload.source_question_id, question_text, answer,
                             explanation, difficulty, category, subcategory,
                             json.dumps(candidate.get("concepts", []), ensure_ascii=False),
                             "valid" if valid else "rejected",
                             json.dumps(issues, ensure_ascii=False), payload.mode))
        return {"id": cursor.lastrowid, "valid": valid, "issues": issues,
                "question": {"id": cursor.lastrowid, "question_text": candidate["question_text"],
                             "category": category, "subcategory": subcategory, "difficulty": difficulty} if valid else None}


@app.get("/api/study/today")
def today():
    with connect() as db:
        return {"items": build_plan(db), "difficulty": suggested_difficulty(db)}


@app.post("/api/study/today/refresh")
def refresh_today():
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        return {"items": build_plan(db, refresh=True), "difficulty": suggested_difficulty(db)}


@app.get("/api/wrong-answers")
def wrong_answers():
    with connect() as db:
        rows = db.execute("""SELECT w.*,q.year,q.round,q.number,q.question_text
                             FROM wrong_answer w LEFT JOIN question q ON q.id=w.question_id
                             WHERE w.user_id=1 ORDER BY w.last_wrong_at DESC LIMIT 100""").fetchall()
        return {"items": [record(row) for row in rows]}


@app.get("/api/theory")
def theories():
    with connect() as db:
        return {"items": [record(row) for row in db.execute("""SELECT m.category,m.subcategory,t.id,t.title,t.summary,
                      t.example,t.common_mistakes,t.source FROM
                      (SELECT DISTINCT category,subcategory FROM question_meta) m
                      LEFT JOIN theory t ON t.category=m.category AND t.subcategory=m.subcategory
                                         AND t.source='local'
                      ORDER BY m.category,m.subcategory""")]}


@app.post("/api/theory/explain")
def explain(payload: TheoryIn):
    if not llm_service.available():
        raise HTTPException(503, ".env에 API 키를 입력하세요.")
    with connect() as db:
        example = db.execute("""SELECT q.question_text FROM question q JOIN question_meta m ON m.question_id=q.id
                              WHERE m.category=? AND m.subcategory=? LIMIT 1""",
                             (payload.category, payload.subcategory)).fetchone()
    try:
        result = llm_service.explain_concept(payload.category, payload.subcategory,
                                             example[0] if example else "")
    except RuntimeError as exc:
        raise ai_http_error(exc) from exc
    if not isinstance(result, dict):
        raise HTTPException(502, "AI 이론 응답 형식이 올바르지 않습니다.")
    result = {field: ai_text(result.get(field)) for field in
              ("title", "summary", "example", "common_mistakes")}
    result["title"] = result["title"] or payload.subcategory
    return result


@app.get("/api/dashboard")
def dashboard():
    with connect() as db:
        attempts = db.execute("SELECT COUNT(*) total,COALESCE(SUM(is_correct),0) correct FROM attempt WHERE is_correct IS NOT NULL").fetchone()
        due = db.execute("SELECT COUNT(*) FROM review_schedule WHERE next_review_at<=?", (now().isoformat(),)).fetchone()[0]
        skills = [record(row) for row in db.execute("SELECT * FROM user_skill ORDER BY score ASC")]
        recent = [record(row) for row in db.execute("""SELECT date(created_at) day,COUNT(*) total,SUM(is_correct) correct
                                                     FROM attempt WHERE is_correct IS NOT NULL
                                                     GROUP BY date(created_at) ORDER BY day DESC LIMIT 14""")]
        return {"attempts": attempts["total"], "correct": attempts["correct"], "due": due,
                "skills": skills, "recent": recent, "difficulty": suggested_difficulty(db)}
