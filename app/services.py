from __future__ import annotations

import json
import random
import re
import sqlite3
from collections import Counter
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
        # A stable daily set: 20 questions distributed across the six current study areas.
        quotas = {"프로그래밍": 6, "데이터베이스": 4, "소프트웨어 공학": 3,
                  "네트워크": 3, "보안": 2, "기타": 2}
        rows = db.execute("""SELECT q.id,q.year,q.round,q.number,m.category,m.subcategory,
                            COALESCE(s.score,0.5) AS skill_score,
                            r.next_review_at,COALESCE(a.attempt_count,0) AS attempt_count
                            FROM question q JOIN question_meta m ON m.question_id=q.id
                            LEFT JOIN user_skill s ON s.user_id=? AND s.category=m.category AND s.subcategory=m.subcategory
                            LEFT JOIN review_schedule r ON r.user_id=? AND r.question_id=q.id
                            LEFT JOIN (SELECT question_id,COUNT(*) AS attempt_count FROM attempt
                                       WHERE user_id=? AND is_correct IS NOT NULL GROUP BY question_id) a ON a.question_id=q.id""",
                          (user_id, user_id, user_id)).fetchall()
        candidates = []
        for row in rows:
            item = dict(row)
            if item["next_review_at"] and item["next_review_at"] <= now().isoformat():
                item["reason"], item["priority"] = "review", 0
            elif item["attempt_count"] == 0 and item["skill_score"] < 0.5:
                item["reason"], item["priority"] = "weak", 2
            elif item["attempt_count"] == 0:
                item["reason"], item["priority"] = "new", 3
            else:
                item["reason"], item["priority"] = "practice", 4
            item["generated"] = False
            candidates.append(item)
        generated = db.execute("""SELECT g.id,g.category,g.subcategory FROM generated_question g
                                  LEFT JOIN attempt a ON a.generated_question_id=g.id AND a.user_id=?
                                  WHERE g.user_id=? AND g.validation_status='valid' AND a.id IS NULL
                                  ORDER BY g.id DESC LIMIT 2""", (user_id, user_id)).fetchall()
        for row in generated:
            candidates.append({"id": row["id"], "category": row["category"],
                               "subcategory": row["subcategory"], "reason": "generated",
                               "priority": 1, "skill_score": 0.5, "year": 0, "round": 0,
                               "number": 0, "generated": True})
        if refresh:
            fresh = [item for item in candidates if (item["generated"], item["id"]) not in previous]
            # Reuse old items only when the entire pool cannot supply 20 different questions.
            candidates = fresh if len(fresh) >= 20 else fresh + [
                item for item in candidates if (item["generated"], item["id"]) in previous]
        random_order = {(item["generated"], item["id"]): random.random() for item in candidates}
        picked = []
        chosen = set()
        selected_years = Counter()

        def take(category: str, count: int, subcategory: str | None = None):
            for _ in range(max(0, count)):
                options = [candidate for candidate in candidates
                           if (candidate["generated"], candidate["id"]) not in chosen
                           and candidate["category"] == category
                           and (subcategory is None or candidate["subcategory"] == subcategory)]
                if not options:
                    break
                candidate = min(options, key=lambda item: (
                    (item["generated"], item["id"]) in previous,
                    item["priority"], selected_years[item["year"]], item["skill_score"],
                    random_order[(item["generated"], item["id"])] if refresh else -item["year"],
                    -item["round"], item["number"]))
                key = (candidate["generated"], candidate["id"])
                picked.append(candidate)
                chosen.add(key)
                selected_years[candidate["year"]] += 1

        for subcategory in ("Java", "Python", "C"):
            take("프로그래밍", 2, subcategory)
        for category, quota in quotas.items():
            current = sum(item["category"] == category for item in picked)
            take(category, quota - current)
        if len(picked) < 20:
            for candidate in candidates:
                key = (candidate["generated"], candidate["id"])
                if key not in chosen:
                    picked.append(candidate); chosen.add(key)
                if len(picked) == 20:
                    break
        for position, item in enumerate(picked[:20], 1):
            db.execute("""INSERT INTO daily_plan(user_id,plan_date,position,question_id,generated_question_id,reason)
                          VALUES(?,?,?,?,?,?)""",
                       (user_id, day, position, None if item["generated"] else item["id"],
                        item["id"] if item["generated"] else None, item["reason"]))
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
            items.append({**dict(row), "reason": plan["reason"], "completed": bool(plan["completed_at"])})
    return items
