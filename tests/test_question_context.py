import sqlite3
import unittest

from app.question_context import audit_image_contexts, save_verified_image_text, verified_image_text


class QuestionContextTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE question(id PRIMARY KEY, year, round, number, question_text, image_urls);
            CREATE TABLE question_context(question_id PRIMARY KEY, fingerprint, transcription);
            INSERT INTO question VALUES(1,2020,1,1,'그림 문제','["first.png","second.png"]');
            INSERT INTO question VALUES(2,2020,1,2,'텍스트 문제','[]');
        ''')
        self.question = self.db.execute("SELECT * FROM question WHERE id=1").fetchone()

    def test_audit_counts_missing_and_ready_questions(self):
        before = audit_image_contexts(self.db)
        self.assertEqual(before["total_questions"], 2)
        self.assertEqual(before["image_count"], 2)
        self.assertEqual(len(before["pending_questions"]), 1)
        save_verified_image_text(self.db, self.question, "첫 번째 그림의 표\n두 번째 그림의 SQL")
        after = audit_image_contexts(self.db)
        self.assertEqual(after["ready_questions"], 1)
        self.assertEqual(after["pending_questions"], [])
        self.assertIn("두 번째", verified_image_text(self.db, self.question))

    def test_added_image_requires_rechecking_all_images(self):
        save_verified_image_text(self.db, self.question, "두 그림을 확인한 내용")
        self.db.execute('UPDATE question SET image_urls=? WHERE id=1', ('["first.png","second.png","new.png"]',))
        self.assertEqual(audit_image_contexts(self.db)["ready_questions"], 0)

    def test_updating_transcription_preserves_question_content(self):
        save_verified_image_text(self.db, self.question, "기존 설명")
        save_verified_image_text(self.db, self.question, "수정한 설명")
        self.assertEqual(verified_image_text(self.db, self.question), "수정한 설명")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM question_context").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT question_text FROM question WHERE id=1").fetchone()[0], "그림 문제")

    def test_empty_transcription_does_not_mark_image_as_ready(self):
        with self.assertRaises(ValueError):
            save_verified_image_text(self.db, self.question, " \n ")
        self.assertEqual(len(audit_image_contexts(self.db)["pending_questions"]), 1)


if __name__ == "__main__":
    unittest.main()
