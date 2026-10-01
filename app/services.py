from __future__ import annotations

import json
import random
import re
import sqlite3
from datetime import datetime, timedelta, timezone


KST = timezone(timedelta(hours=9))
INTERVALS = (1, 3, 7, 14)


def now() -> datetime:
    return datetime.now(KST)


def normalize(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"\s+", "", value)
    return re.sub(r"[.,。·ㆍ()\[\]{}]", "", value)


def grade(user_answer: str, correct_answer: str) -> tuple[bool | None, str]:
    # Long answer blocks can contain an explanation; require learner confirmation.
    if (len(correct_answer) > 60 or "\n" in correct_answer or
            re.search(r"\b2[.)]", correct_answer) or len(user_answer.strip()) > 100):
        return None, "self_review"
    variants = [correct_answer]
    match = re.fullmatch(r"\s*(.+?)\s*\(([^()]+)\)\s*", correct_answer)
    if match:
        variants.extend([match[1], match[2]])
    if "/" in correct_answer and len(correct_answer) < 60:
        variants += correct_answer.split("/")
    normalized = normalize(user_answer)
    return normalized in {normalize(item) for item in variants}, "exact"


def suggested_difficulty(db: sqlite3.Connection, user_id: int = 1) -> int:
    recent = db.execute("SELECT is_correct FROM attempt WHERE user_id=? AND is_correct IS NOT NULL ORDER BY id DESC LIMIT 5", (user_id,)).fetchall()
    if len(recent) < 5:
        return 3
    rate = sum(row["is_correct"] for row in recent) / 5
    current = db.execute("SELECT AVG(m.difficulty) FROM attempt a JOIN question_meta m ON m.question_id=a.question_id WHERE a.user_id=? ORDER BY a.id DESC LIMIT 5", (user_id,)).fetchone()[0] or 3
    return max(1, min(5, round(current) + (1 if rate >= .8 else -1 if rate <= .4 else 0)))


def complete_attempt(db: sqlite3.Connection, attempt_id: int, correct: bool):
    attempt = db.execute("""SELECT a.*, m.category, m.subcategory
                            FROM attempt a LEFT JOIN question_meta m ON a.question_id=m.question_id
                            WHERE a.id=?""", (attempt_id,)).fetchone()
    if attempt is None:
        raise ValueError("풀이 기록을 찾을 수 없습니다.")
    if attempt["is_correct"] is not None:
        raise ValueError("이미 채점된 풀이입니다.")
    db.execute("UPDATE attempt SET is_correct=? WHERE id=?", (int(correct), attempt_id))
    if attempt["mode"] == "today":
        db.execute("""UPDATE daily_plan SET completed_at=? WHERE user_id=? AND plan_date=?
                      AND question_id IS ? AND generated_question_id IS ?""",
                   (now().isoformat(), attempt["user_id"], now().date().isoformat(),
                    attempt["question_id"], attempt["generated_question_id"]))
    category, subcategory = attempt["category"], attempt["subcategory"]
    if attempt["generated_question_id"]:
        generated = db.execute("SELECT category,subcategory FROM generated_question WHERE id=?", (attempt["generated_question_id"],)).fetchone()
        category, subcategory = generated["category"], generated["subcategory"]
    category, subcategory = category or "기타", subcategory or "기본 개념"
    stamp = now()
    db.execute("""INSERT INTO user_skill(user_id,category,subcategory,score,correct_count,wrong_count,last_updated)
                  VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,category,subcategory) DO UPDATE SET
                  score=MIN(1,MAX(0,user_skill.score+excluded.score-0.5)),
                  correct_count=user_skill.correct_count+excluded.correct_count,
                  wrong_count=user_skill.wrong_count+excluded.wrong_count,
                  last_updated=excluded.last_updated""",
               (attempt["user_id"], category, subcategory, 0.58 if correct else 0.36,
                int(correct), int(not correct), stamp.isoformat()))
    question_id = attempt["question_id"]
    generated_id = attempt["generated_question_id"]
    id_column = "generated_question_id" if generated_id else "question_id"
    item_id = generated_id or question_id
    schedule = db.execute(f"SELECT interval_index FROM review_schedule WHERE user_id=? AND {id_column}=?",
                          (attempt["user_id"], item_id)).fetchone()
    interval_index = min(3, (schedule["interval_index"] + 1) if schedule else 1) if correct else 0
    due = stamp + timedelta(days=INTERVALS[interval_index])
    db.execute(f"""INSERT INTO review_schedule(user_id,question_id,generated_question_id,interval_index,next_review_at,last_result)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,{id_column}) DO UPDATE SET
                   interval_index=excluded.interval_index,next_review_at=excluded.next_review_at,
                   last_result=excluded.last_result""",
               (attempt["user_id"], question_id, generated_id, interval_index, due.isoformat(), int(correct)))
    if not correct:
        db.execute(f"""INSERT INTO wrong_answer(user_id,question_id,generated_question_id,last_attempt_id,
                         user_answer,last_wrong_at,next_review_at) VALUES(?,?,?,?,?,?,?)
                         ON CONFLICT(user_id,{id_column}) DO UPDATE SET
                         last_attempt_id=excluded.last_attempt_id,user_answer=excluded.user_answer,
                         wrong_count=wrong_answer.wrong_count+1,last_wrong_at=excluded.last_wrong_at,
                         next_review_at=excluded.next_review_at""",
                   (attempt["user_id"], question_id, generated_id, attempt_id,
                    attempt["user_answer"], stamp.isoformat(), due.isoformat()))
    return {"is_correct": correct, "next_review_at": due.isoformat(),
            "category": category, "subcategory": subcategory,
            "suggested_difficulty": suggested_difficulty(db, attempt["user_id"])}


def build_plan(db: sqlite3.Connection, user_id: int = 1, refresh: bool = False):
    day = now().date().isoformat()
    saved = db.execute("SELECT * FROM daily_plan WHERE user_id=? AND plan_date=? ORDER BY position",
                       (user_id, day)).fetchall()
    previous = set()
    if refresh:
        previous = {(row["question_id"] is None, row["generated_question_id"]
                     if row["question_id"] is None else row["question_id"]) for row in saved}
        db.execute("DELETE FROM daily_plan WHERE user_id=? AND plan_date=?", (user_id, day))
        saved = []
    if not saved:
        quotas = {"프로그래밍": 6, "데이터베이스": 4, "소프트웨어 공학": 3,
                  "네트워크": 3, "보안": 2, "기타": 2}
        rows = db.execute("""SELECT q.id,q.year,q.round,q.number,m.category,m.subcategory,
                            COALESCE(a.attempt_count,0) AS attempt_count
                            FROM question q JOIN question_meta m ON m.question_id=q.id
                            LEFT JOIN (SELECT question_id,COUNT(*) AS attempt_count FROM attempt
                                       WHERE user_id=? GROUP BY question_id) a ON a.question_id=q.id""",
                          (user_id,)).fetchall()
        source = [{**dict(row), "generated": False} for row in rows]
        reviews = [item for item in source if item["attempt_count"]]
        fresh = [item for item in source if not item["attempt_count"]]
        generated_reviews = db.execute("""SELECT g.id,g.category,g.subcategory FROM generated_question g
            WHERE g.user_id=? AND g.validation_status='valid' AND EXISTS
            (SELECT 1 FROM attempt a WHERE a.user_id=? AND a.generated_question_id=g.id)""",
            (user_id, user_id)).fetchall()
        reviews += [{**dict(row), "generated": True} for row in generated_reviews]

        def preferred(pool):
            unused = [item for item in pool if (item["generated"], item["id"]) not in previous]
            used = [item for item in pool if (item["generated"], item["id"]) in previous]
            random.shuffle(unused)
            random.shuffle(used)
            return unused + used

        review_count = min(random.randint(3, 5), len(reviews))
        picked_reviews = preferred(reviews)[:review_count]
        fresh = preferred(fresh)
        new_count = min(20 - review_count, len(fresh))
        picked_new = []
        remaining = fresh[:]
        for category, quota in quotas.items():
            target = min(round(quota * new_count / 20), new_count - len(picked_new))
            matches = [item for item in remaining if item["category"] == category][:target]
            picked_new.extend(matches)
            selected_ids = {item["id"] for item in matches}
            remaining = [item for item in remaining if item["id"] not in selected_ids]
        picked_new.extend(remaining[:new_count - len(picked_new)])
        picked = [(item, "review") for item in picked_reviews] + [(item, "new") for item in picked_new]
        for position, (item, reason) in enumerate(picked, 1):
            db.execute("""INSERT INTO daily_plan(user_id,plan_date,position,question_id,generated_question_id,reason)
                          VALUES(?,?,?,?,?,?)""",
                       (user_id, day, position, None if item["generated"] else item["id"],
                        item["id"] if item["generated"] else None, reason))
        saved = db.execute("SELECT * FROM daily_plan WHERE user_id=? AND plan_date=? ORDER BY position",
                           (user_id, day)).fetchall()
    items = []
    for plan in saved:
        if plan["question_id"]:
            row = db.execute("""SELECT q.id,q.year,q.round,q.number,substr(q.question_text,1,150) AS preview,
                               m.category,m.subcategory FROM question q JOIN question_meta m ON m.question_id=q.id
                               WHERE q.id=?""", (plan["question_id"],)).fetchone()
        else:
            row = db.execute("""SELECT id,NULL AS year,NULL AS round,NULL AS number,
                               substr(question_text,1,150) AS preview,category,subcategory
                               FROM generated_question WHERE id=?""", (plan["generated_question_id"],)).fetchone()
        if row:
            items.append({**dict(row), "reason": plan["reason"],
                          "generated": plan["question_id"] is None,
                          "completed": bool(plan["completed_at"])})
    return items
