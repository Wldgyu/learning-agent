import sqlite3
import unittest
from unittest.mock import patch

from app.services import build_plan


class DailyPlanTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE question(id INTEGER PRIMARY KEY,year INTEGER,round INTEGER,number INTEGER,question_text TEXT);
            CREATE TABLE question_meta(question_id INTEGER,category TEXT,subcategory TEXT);
            CREATE TABLE attempt(id INTEGER PRIMARY KEY,user_id INTEGER,question_id INTEGER,generated_question_id INTEGER);
            CREATE TABLE generated_question(id INTEGER PRIMARY KEY,user_id INTEGER,question_text TEXT,
                category TEXT,subcategory TEXT,validation_status TEXT);
            CREATE TABLE daily_plan(user_id INTEGER,plan_date TEXT,position INTEGER,question_id INTEGER,
                generated_question_id INTEGER,reason TEXT,completed_at TEXT);
        """)
        for number in range(1, 51):
            self.db.execute("INSERT INTO question VALUES(?,?,?,?,?)", (number, 2025, 1, number, f"기출 {number}"))
            self.db.execute("INSERT INTO question_meta VALUES(?,?,?)", (number, "프로그래밍", "Java"))
        for number in range(1, 9):
            self.db.execute("INSERT INTO attempt(user_id,question_id) VALUES(1,?)", (number,))
        self.db.execute("INSERT INTO generated_question VALUES(1,1,'AI 문제','보안','기본','valid')")
        self.db.execute("INSERT INTO attempt(user_id,generated_question_id) VALUES(1,1)")

    def tearDown(self):
        self.db.close()

    def test_refresh_keeps_three_to_five_reviews_and_uses_unseen_sources(self):
        with patch("app.services.random.randint", return_value=4):
            first = build_plan(self.db)
            second = build_plan(self.db, refresh=True)
        for plan in (first, second):
            self.assertEqual(len(plan), 20)
            self.assertEqual(sum(item["reason"] == "review" for item in plan), 4)
            self.assertTrue(all(item["reason"] == "review" for item in plan[:4]))
            self.assertTrue(all(item["id"] > 8 and not item["generated"]
                                for item in plan if item["reason"] == "new"))
            self.assertTrue(all(item["id"] <= 8 or item["generated"]
                                for item in plan if item["reason"] == "review"))
        first_new = {item["id"] for item in first if item["reason"] == "new"}
        second_new = {item["id"] for item in second if item["reason"] == "new"}
        self.assertFalse(first_new & second_new)


if __name__ == "__main__":
    unittest.main()
