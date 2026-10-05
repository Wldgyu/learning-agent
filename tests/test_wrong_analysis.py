import unittest
from unittest.mock import patch

from app.main import wrong_answers, analyze_wrongs, theories, delete_theory, WrongAnalyzeIn, WrongTypeItem


class WrongAnalysisApiTests(unittest.TestCase):
    def test_wrong_answers_returns_categories(self):
        data = wrong_answers()
        self.assertIn("items", data)
        if data["items"]:
            first = data["items"][0]
            self.assertIn("category", first)
            self.assertIn("subcategory", first)
            self.assertIn("question_text", first)

    def test_theory_list_and_delete(self):
        data = theories()
        self.assertIn("items", data)
        self.assertTrue(len(data["items"]) >= 8)
        first = data["items"][0]
        self.assertIn("title", first)
        self.assertIn("memorization_tip", first)
        self.assertIn("source", first)

    @patch("app.llm_service.available", return_value=True)
    @patch("app.llm_service.analyze_wrong_types")
    def test_analyze_wrongs_creates_theory(self, mock_analyze, mock_avail):
        mock_analyze.return_value = [
            {
                "category": "프로그래밍",
                "subcategory": "Java",
                "title": "Java 오버라이딩 테스트",
                "summary": "오버라이딩 시 실제 객체 타입의 메서드가 호출됩니다.",
                "memorization_tip": "선언은 부모, 실행은 자식!",
                "common_mistakes": "오버로딩과 오버라이딩 혼동",
                "example": "Parent p = new Child();"
            }
        ]

        payload = WrongAnalyzeIn(
            types=[WrongTypeItem(category="프로그래밍", subcategory="Java")],
            wrong_ids=[]
        )
        res_data = analyze_wrongs(payload)
        self.assertIn("items", res_data)
        self.assertEqual(len(res_data["items"]), 1)
        created_theory = res_data["items"][0]
        self.assertEqual(created_theory["title"], "Java 오버라이딩 테스트")
        self.assertEqual(created_theory["source"], "ai_wrong_analysis")
        theory_id = created_theory["id"]

        # Verify it shows up in theories()
        theory_res = theories()
        found = any(t["id"] == theory_id for t in theory_res["items"])
        self.assertTrue(found)

        # Delete it to clean up
        del_res = delete_theory(theory_id)
        self.assertTrue(del_res["ok"])

        # Verify it is deleted
        theory_res_after = theories()
        found_after = any(t["id"] == theory_id for t in theory_res_after["items"])
        self.assertFalse(found_after)


if __name__ == "__main__":
    unittest.main()
