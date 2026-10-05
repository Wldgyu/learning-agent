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
        CREATE TABLE IF NOT EXISTS question_context (
          question_id INTEGER PRIMARY KEY REFERENCES question(id),
          fingerprint TEXT NOT NULL, transcription TEXT NOT NULL
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
          id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL, subcategory TEXT NOT NULL,
          title TEXT NOT NULL, summary TEXT NOT NULL, example TEXT NOT NULL DEFAULT '',
          common_mistakes TEXT NOT NULL DEFAULT '', memorization_tip TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT 'local', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
        # Migrate theory table if needed
        cols = [r["name"] for r in db.execute("PRAGMA table_info(theory)").fetchall()]
        sql_row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='theory'").fetchone()
        has_strict_unique = sql_row and "UNIQUE(category, subcategory)" in sql_row["sql"]
        if "memorization_tip" not in cols or has_strict_unique:
            db.execute("""
                CREATE TABLE IF NOT EXISTS theory_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    subcategory TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    example TEXT NOT NULL DEFAULT '',
                    common_mistakes TEXT NOT NULL DEFAULT '',
                    memorization_tip TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'local',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            select_mem = "memorization_tip" if "memorization_tip" in cols else "''"
            select_created = "created_at" if "created_at" in cols else "CURRENT_TIMESTAMP"
            db.execute(f"""
                INSERT INTO theory_new (id, category, subcategory, title, summary, example, common_mistakes, memorization_tip, source, created_at)
                SELECT id, category, subcategory, title, summary, example, common_mistakes, {select_mem}, source, {select_created}
                FROM theory
            """)
            db.execute("DROP TABLE theory")
            db.execute("ALTER TABLE theory_new RENAME TO theory")
        db.execute("CREATE INDEX IF NOT EXISTS idx_theory_category ON theory(category, subcategory)")

        for row in db.execute("SELECT q.id, q.question_text FROM question q LEFT JOIN question_meta m ON m.question_id=q.id WHERE m.question_id IS NULL"):
            category, subcategory = classify(row["question_text"])
            db.execute("INSERT INTO question_meta(question_id, category, subcategory) VALUES(?,?,?)",
                       (row["id"], category, subcategory))

        base_theories = [
            ("프로그래밍", "Java", "Java 객체지향 & 코드 실행 원리",
             "오버로딩은 인자(타입/개수)로 컴파일 시점에 결정되고, 오버라이딩은 런타임에 실제 생성된 객체의 메서드가 동적으로 호출됩니다.",
             "Parent p = new Child(); // p.method() 호출 시 Child의 오버라이딩 메서드 실행",
             "문자열 결합(+)과 정수 덧셈의 연산 우선순위 주의: \"결과:\" + 1 + 2 는 \"결과:12\"가 됩니다.",
             "💡 [Java 암기 팁]\n- '오버로딩(Overloading)' = 과적(이름 같고 짐/매개변수가 다름)\n- '오버라이딩(Overriding)' = 덮어쓰기(상속받아 재정의)\n- 자식 객체 생성 시 부모 생성자(super())가 먼저 실행!"),
            ("데이터베이스", "SQL·설계", "SQL 연산 순서 & 집계 함수 원리",
             "SQL 실행 순서는 FROM → ON → JOIN → WHERE → GROUP BY → HAVING → SELECT → DISTINCT → ORDER BY 순서로 평가됩니다.",
             "SELECT dept, COUNT(*) FROM emp WHERE salary >= 3000 GROUP BY dept HAVING COUNT(*) >= 2;",
             "GROUP BY에 지정하지 않은 일반 컬럼을 SELECT 절에 단독으로 쓰는 실수 주의.",
             "💡 [SQL 실행 순서 암기: 프온조웨 그해셀디옵]\n- WHERE 절에는 집계 함수(COUNT, SUM 등) 사용 불가 → HAVING 절 사용!\n- COUNT(*)는 NULL 포함 전체 행 수, COUNT(컬럼)은 NULL 제외 행 수"),
            ("프로그래밍", "C", "C 언어 포인터 & 배열 연산 핵심",
             "포인터 변수는 주소값을 저장하며, *p는 역참조(값), &x는 주소 추출입니다. 배열 이름은 첫 번째 요소의 시작 주소를 나타냅니다.",
             "int arr[3] = {10, 20, 30}; int *p = arr; *(p+1) == 20;",
             "연산자 우선순위 착각: 증감 연산자(++)와 역참조(*) 우선순위를 괄호 없이 혼동하지 말 것.",
             "💡 [C 포인터 암기 팁]\n- *p++: 현재 p가 가리키는 값을 읽은 후 p의 주소 1 증가\n- (*p)++: p가 가리키는 실제 데이터 값을 1 증가\n- 문자열 끝에는 항상 널 문자('\\0')가 포함됨을 계산!"),
            ("프로그래밍", "Python", "Python 슬라이싱 & 컬렉션 다루기",
             "Python 슬라이싱은 [시작:끝:간격] 형태로 동작하며, '끝' 인덱스는 포함되지 않습니다. 음수 인덱스는 뒤에서부터 -1로 카운트합니다.",
             "nums = [10, 20, 30, 40, 50]; print(nums[1:4]) # [20, 30, 40]",
             "인덱스 범위 착각: [1:3]은 인덱스 1과 2만 포함되고 3은 제외됩니다.",
             "💡 [Python 암기 팁]\n- s[::-1]: 문자열 전체 역순 뒤집기\n- list.pop(): 맨 뒤 요소 꺼내기, list.append(): 맨 뒤 추가\n- set은 중복 불허, dictionary는 key-value 쌍"),
            ("소프트웨어 공학", "개발·테스트", "결합도·응집도 & 소프트웨어 테스트",
             "모듈의 독립성을 높이려면 '응집도는 높이고(High Cohesion), 결합도는 낮춰야(Low Coupling)' 합니다.",
             "화이트박스 테스트: 문장/분기/조건 커버리지\n블랙박스 테스트: 동등분할, 경계값 분석, 원인-효과 그래프",
             "응집도와 결합도의 순서를 반대로 외우거나, 블랙박스 테스트와 화이트박스 기법 종류를 섞어 쓰는 실수 주의.",
             "💡 [두문자 암기 비법]\n- 응집도(약함→강함): 우 논 시 절 통 순 기 (우연, 논리, 시간, 절차, 통신, 순차, 기능)\n- 결합도(약함/좋음→강함/나쁨): 자 스 제 외 공 내 (자료, 스탬프, 제어, 외부, 공통, 내용)"),
            ("네트워크", "네트워크 개념", "OSI 7계층 & IP 서브넷 계산",
             "OSI 7계층은 물리, 데이터링크, 네트워크, 전송, 세션, 표현, 응용 계층으로 구성되며, 각 계층마다 고유 프로토콜과 전송 단위가 있습니다.",
             "/24 서브넷: 255.255.255.0 (호스트 254개)\n/26 서브넷: 255.255.255.192 (서브넷 4개, 호스트 62개씩)",
             "네트워크 주소(첫 번째)와 브로드캐스트 주소(마지막) 2개는 호스트로 사용할 수 없으므로 호스트 개수 계산 시 항상 -2를 해야 합니다.",
             "💡 [네트워크 암기 비법]\n- OSI 7계층(하위→상위): 물 데 네 전 세 표 응\n- 전송 계층 단위: 세그먼트(TCP/UDP)\n- 네트워크 계층 단위: 패킷(IP/라우터)\n- 데이터링크 단위: 프레임(MAC/스위치)"),
            ("보안", "보안 개념", "보안 3대 요소 & 암호 알고리즘",
             "정보보안의 3대 요소는 기밀성(Confidentiality), 무결성(Integrity), 가용성(Availability)이며, 암호화는 대칭키와 비대칭키(공개키)로 구분됩니다.",
             "대칭키 블록 암호: DES(64비트), AES(128/192/256비트), SEED(한국 KISA, 128비트), ARIA(국정원)",
             "RSA를 대칭키로 혼동하거나, 해시 함수를 양방향 복호화가 가능한 암호화로 착각하는 실수.",
             "💡 [보안 암기 비법: 기무가]\n- 대칭키(비밀키): 속도 빠름, 키 배송 문제 (DES, AES, SEED, ARIA)\n- 비대칭키(공개키): 속도 느림, 키 관리 용이 (RSA, ECC, 디피-헬만)\n- 무결성 검증: 해시 함수 (SHA, MD5)"),
            ("기타", "기본 개념", "정보처리기사 신기술 및 핵심 표준",
             "데이터 웨어하우스, 빅데이터, 클라우드 컴퓨팅 및 소프트웨어 아키텍처 패턴의 기본 개념을 정리합니다.",
             "아키텍처 패턴: 계층(Layer), 클라이언트-서버, 파이프-필터, MVC 패턴",
             "ACID 특성 중 원자성(All or Nothing)과 일관성의 차이를 혼동하지 않기.",
             "💡 [핵심 용어 암기]\n- ETL: 추출(Extract) → 변환(Transform) → 적재(Load)\n- 트랜잭션 4대 특성(ACID): 원자성(Atomicity), 일관성(Consistency), 격리성(Isolation), 지속성(Durability)")
        ]
        # Clean up old single 'SQL' subcategory to 'SQL·설계' if present
        db.execute("UPDATE theory SET subcategory='SQL·설계' WHERE category='데이터베이스' AND subcategory='SQL'")
        for cat, subcat, title, summary, example, mistakes, mem in base_theories:
            existing = db.execute("SELECT id FROM theory WHERE category=? AND subcategory=? AND source='local'", (cat, subcat)).fetchone()
            if not existing:
                db.execute("""INSERT INTO theory(category, subcategory, title, summary, example, common_mistakes, memorization_tip, source)
                              VALUES(?,?,?,?,?,?,?,?)""", (cat, subcat, title, summary, example, mistakes, mem, 'local'))
            else:
                db.execute("""UPDATE theory SET title=?, summary=?, example=?, common_mistakes=?, memorization_tip=?
                              WHERE id=?""", (title, summary, example, mistakes, mem, existing["id"]))


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
