from __future__ import annotations

import sqlite3
import re
from contextlib import contextmanager
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent.parent / "questions.sqlite3"


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS source_page (
          year INTEGER NOT NULL, round INTEGER NOT NULL, url TEXT NOT NULL,
          html_sha256 TEXT NOT NULL, imported_at TEXT NOT NULL,
          question_count INTEGER NOT NULL, PRIMARY KEY (year, round)
        );
        CREATE TABLE IF NOT EXISTS question (
          id INTEGER PRIMARY KEY, year INTEGER NOT NULL, round INTEGER NOT NULL,
          number INTEGER NOT NULL, question_text TEXT NOT NULL, answer TEXT NOT NULL,
          question_html TEXT NOT NULL, answer_html TEXT NOT NULL,
          image_urls TEXT NOT NULL, review_flags TEXT NOT NULL,
          source_url TEXT NOT NULL, source_kind TEXT NOT NULL DEFAULT '복원문제',
          UNIQUE (year, round, number),
          FOREIGN KEY (year, round) REFERENCES source_page(year, round)
        );
        CREATE TABLE IF NOT EXISTS question_meta (
          question_id INTEGER PRIMARY KEY REFERENCES question(id),
          category TEXT NOT NULL, subcategory TEXT NOT NULL,
          difficulty INTEGER NOT NULL DEFAULT 3 CHECK(difficulty BETWEEN 1 AND 5)
        );
        CREATE TABLE IF NOT EXISTS attempt (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL DEFAULT 1,
          question_id INTEGER REFERENCES question(id),
          generated_question_id INTEGER,
          user_answer TEXT NOT NULL, correct_answer TEXT NOT NULL,
          is_correct INTEGER, grading_method TEXT NOT NULL,
          elapsed_seconds INTEGER NOT NULL DEFAULT 0,
          mode TEXT NOT NULL DEFAULT 'source', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS wrong_answer (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL DEFAULT 1,
          question_id INTEGER, generated_question_id INTEGER,
          last_attempt_id INTEGER NOT NULL REFERENCES attempt(id),
          user_answer TEXT NOT NULL, wrong_reason TEXT,
          weak_concept TEXT, wrong_count INTEGER NOT NULL DEFAULT 1,
          last_wrong_at TEXT NOT NULL, next_review_at TEXT NOT NULL,
          UNIQUE(user_id, question_id), UNIQUE(user_id, generated_question_id)
        );
        CREATE TABLE IF NOT EXISTS user_skill (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL DEFAULT 1,
          category TEXT NOT NULL, subcategory TEXT NOT NULL,
          score REAL NOT NULL DEFAULT 0.5, correct_count INTEGER NOT NULL DEFAULT 0,
          wrong_count INTEGER NOT NULL DEFAULT 0, last_updated TEXT NOT NULL,
          UNIQUE(user_id, category, subcategory)
        );
        CREATE TABLE IF NOT EXISTS review_schedule (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL DEFAULT 1,
          question_id INTEGER, generated_question_id INTEGER,
          interval_index INTEGER NOT NULL DEFAULT 0,
          next_review_at TEXT NOT NULL, last_result INTEGER NOT NULL,
          UNIQUE(user_id, question_id), UNIQUE(user_id, generated_question_id)
        );
        CREATE TABLE IF NOT EXISTS daily_plan (
          user_id INTEGER NOT NULL DEFAULT 1, plan_date TEXT NOT NULL,
          position INTEGER NOT NULL, question_id INTEGER REFERENCES question(id),
          generated_question_id INTEGER, reason TEXT NOT NULL,
          completed_at TEXT, PRIMARY KEY(user_id, plan_date, position)
        );
        CREATE TABLE IF NOT EXISTS theory (
          id INTEGER PRIMARY KEY, category TEXT NOT NULL, subcategory TEXT NOT NULL,
          title TEXT NOT NULL, summary TEXT NOT NULL, example TEXT NOT NULL DEFAULT '',
          common_mistakes TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'local',
          UNIQUE(category, subcategory)
        );
        CREATE TABLE IF NOT EXISTS generated_question (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL DEFAULT 1,
          source_question_id INTEGER REFERENCES question(id),
          question_text TEXT NOT NULL, answer TEXT NOT NULL,
          explanation TEXT NOT NULL DEFAULT '', difficulty INTEGER NOT NULL DEFAULT 3,
          category TEXT NOT NULL, subcategory TEXT NOT NULL,
          concepts TEXT NOT NULL DEFAULT '[]', validation_status TEXT NOT NULL,
          validation_issues TEXT NOT NULL DEFAULT '[]', mode TEXT NOT NULL DEFAULT 'similar',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_attempt_question ON attempt(user_id, question_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_review_due ON review_schedule(user_id, next_review_at);
        CREATE INDEX IF NOT EXISTS idx_meta_category ON question_meta(category, subcategory);
        """)
        for row in db.execute("SELECT q.id, q.question_text FROM question q LEFT JOIN question_meta m ON m.question_id=q.id WHERE m.question_id IS NULL"):
            category, subcategory = classify(row["question_text"])
            db.execute("INSERT INTO question_meta(question_id, category, subcategory) VALUES(?,?,?)",
                       (row["id"], category, subcategory))
        db.execute("INSERT OR IGNORE INTO theory(category,subcategory,title,summary,example,common_mistakes) VALUES(?,?,?,?,?,?)",
                   ("프로그래밍", "Java", "Java 코드 읽기", "오버로딩은 인자 타입으로 컴파일 시 선택되고, 오버라이딩은 실제 객체 타입에 따라 실행됩니다.", "상속 관계에서 참조 타입과 객체 타입을 구분해 메서드 호출을 추적합니다.", "문자열 결합과 정수 덧셈의 평가 순서를 혼동하지 마세요."))
        db.execute("INSERT OR IGNORE INTO theory(category,subcategory,title,summary,example,common_mistakes) VALUES(?,?,?,?,?,?)",
                   ("데이터베이스", "SQL", "SQL 결과 추적", "FROM, JOIN, WHERE, GROUP BY, SELECT 순서로 중간 결과를 살펴보세요.", "COUNT(*)는 행 수를, COUNT(DISTINCT x)는 서로 다른 x 값을 셉니다.", "집계 함수가 반환하는 한 행과 집계 대상 행 수를 구분하세요."))


def classify(text: str) -> tuple[str, str]:
    lower = text.lower()
    if any(x in lower for x in ("java", "자바", "public class", "system.out")):
        return "프로그래밍", "Java"
    if any(x in lower for x in ("c언어", "#include", "printf(", "struct ")):
        return "프로그래밍", "C"
    if any(x in lower for x in ("python", "파이썬", "print(")) or re.search(r"\bdef\s+\w+\s*\(", lower):
        return "프로그래밍", "Python"
    if any(x in lower for x in ("블랙박스", "화이트박스", "결합도", "응집도", "디자인 패턴", "테스트 기법", "비기능적 요구사항", "기능적 요구사항")):
        return "소프트웨어 공학", "개발·테스트"
    if any(x in lower for x in ("sql", "select ", "테이블", "정규화", "정규형", "dbms", "데이터베이스")):
        return "데이터베이스", "SQL·설계"
    if any(x in lower for x in ("보안", "공격", "암호", "인증", "취약점")):
        return "보안", "보안 개념"
    if any(x in lower for x in ("ip", "라우팅", "네트워크", "프로토콜", "tcp")):
        return "네트워크", "네트워크 개념"
    if any(x in lower for x in ("테스트", "요구사항", "설계", "결합도", "응집도")):
        return "소프트웨어 공학", "개발·테스트"
    return "기타", "기본 개념"
