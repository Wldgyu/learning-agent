import json
import sqlite3
import unittest
from unittest.mock import patch

from app import llm_service
from app.question_context import context_fingerprint, verified_image_text


def explanation(text="검산한 풀이"):
    return {"feedback": "정답을 설명합니다.", "steps": [text, "결론을 확인합니다."],
            "next_tip": "조건을 확인하세요.", "weak_concepts": ["핵심 개념"]}


class FeedbackTests(unittest.TestCase):
    def test_truncated_response_gets_one_retry_with_more_room(self):
        good = {"feedback": "완전한 한국어 해설입니다."}
        with patch.object(llm_service, "_request_json", side_effect=[llm_service.ResponseFormatError("잘림"), good]) as request:
            self.assertEqual(llm_service.ask_json("역할", "자료", 2600), good)
            self.assertEqual(request.call_args.args[2], 5200)
            self.assertEqual(request.call_count, 2)

    def test_mixed_japanese_is_regenerated_once(self):
        bad = {"feedback": "조건을 적용하고 その結果를 셉니다."}
        good = {"feedback": "조건에 맞는 조합 네 개를 셉니다."}
        with patch.object(llm_service, "_request_json", side_effect=[bad, good]) as request:
            self.assertEqual(llm_service.ask_json("역할", "자료"), good)
            self.assertEqual(request.call_count, 2)

    def test_persistent_foreign_prose_is_not_displayed(self):
        with patch.object(llm_service, "_request_json", return_value={"steps": ["その結果"]}) as request:
            with self.assertRaisesRegex(RuntimeError, "한국어"):
                llm_service.ask_json("역할", "자료")
            self.assertEqual(request.call_count, 2)

    def test_literal_code_and_answers_are_preserved(self):
        result = {"answer": "東京", "example": '```sql\nSELECT "東京";\n```\n문자열 `その結果`를 출력합니다.'}
        with patch.object(llm_service, "_request_json", return_value=result) as request:
            self.assertEqual(llm_service.ask_json("역할", "자료"), result)
            request.assert_called_once()

    def test_missing_images_do_not_trigger_a_guessed_explanation(self):
        with patch.object(llm_service, "_request_json") as request:
            result = llm_service.analyze_wrong("이미지 문제", "4", "6", "DB", "SQL", missing_image_context=True)
            request.assert_not_called()
            self.assertEqual(result["steps"], [])
            self.assertIn("전달되지 않아", result["cause"])

    def test_verified_context_reaches_model(self):
        with patch.object(llm_service, "_request_json", side_effect=[explanation(), {"valid": True, "issues": []}]) as request:
            result = llm_service.analyze_wrong("문제", "4", "오답표식", "DB", "SQL", image_context="표와 SQL")
            payload = json.loads(request.call_args_list[0].args[1])
            self.assertEqual(payload["verified_image_text"], "표와 SQL")
            for call in request.call_args_list:
                self.assertNotIn("오답표식", call.args[1])
                self.assertNotIn('"cause"', call.args[1])
                self.assertNotIn('"user_answer"', call.args[1])
            self.assertIn("오답표식", result["cause"])
            self.assertEqual(request.call_count, 2)

    def test_analysis_schema_failure_is_retried_before_review(self):
        bad = {**explanation(), "steps": "배열이 아닌 문자열"}
        with patch.object(llm_service, "_request_json", side_effect=[bad, explanation(), {"valid": True, "issues": []}]) as request:
            result = llm_service.analyze_wrong("문제", "4", "6", "DB", "SQL")
            self.assertEqual(len(result["steps"]), 2)
            self.assertEqual(request.call_count, 3)

    def test_review_boolean_string_is_retried_as_format_error(self):
        with patch.object(llm_service, "_request_json", side_effect=[explanation(), {"valid": "true", "issues": []}, {"valid": True, "issues": []}]) as request:
            result = llm_service.analyze_wrong("문제", "4", "6", "DB", "SQL")
            self.assertEqual(result["feedback"], explanation()["feedback"])
            self.assertEqual(request.call_count, 3)

    def test_review_contradictory_status_is_rejected(self):
        for verdict in ({"valid": True, "issues": ["틀림"]}, {"valid": False, "issues": []}):
            with self.subTest(verdict=verdict), self.assertRaises(llm_service.ResponseFormatError):
                llm_service.validate_review_shape(verdict)

    def test_incorrect_explanation_is_corrected_and_rechecked(self):
        bad = explanation("근거 없는 풀이")
        good = explanation()
        with patch.object(llm_service, "ask_json", side_effect=[bad, {"valid": False, "issues": ["개수 불일치"]}, good, {"valid": True}]) as request:
            result = llm_service.analyze_wrong("문제", "4", "6", "DB", "SQL")
            self.assertEqual(result["steps"], good["steps"])
            self.assertIn("개수 불일치", request.call_args_list[2].args[1])
            self.assertIn("단정할 수는 없습니다", result["cause"])
            self.assertIn("입력한 답: 6", result["cause"])

    def test_failed_verification_does_not_publish_feedback(self):
        with patch.object(llm_service, "ask_json", side_effect=[explanation(), {"valid": False, "issues": ["틀린 계산"]}] * 2):
            with self.assertRaisesRegex(RuntimeError, "정확성 검수"):
                llm_service.analyze_wrong("문제", "4", "6", "DB", "SQL")

    def test_changed_question_invalidates_transcription(self):
        question = {"id": 1, "question_text": "문제", "image_urls": '["image.png"]'}
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        try:
            db.execute("CREATE TABLE question_context(question_id, fingerprint, transcription)")
            db.execute("INSERT INTO question_context VALUES(?,?,?)", (1, context_fingerprint(question), "확인한 표"))
            self.assertEqual(verified_image_text(db, question), "확인한 표")
            question["image_urls"] = '["changed.png"]'
            self.assertEqual(verified_image_text(db, question), "")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
