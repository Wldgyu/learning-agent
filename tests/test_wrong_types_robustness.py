import http.client
import io
import json
import unittest
from unittest.mock import Mock, patch

from app import llm_service as llm


def group(**question):
    base = {"question": "문제", "correct_answer": "정답", "user_answer": "오답",
            "wrong_reason": None, "weak_concept": None}
    base.update(question)
    return {"category": "프로그래밍", "subcategory": "Java", "wrong_questions": [base]}


CARD = {"category": "프로그래밍", "subcategory": "Java", "title": "제목",
        "summary": "요약", "detailed_explanation": "상세", "memorization_tip": "팁",
        "common_mistakes": "실수", "example": "예시"}


class AnalyzeWrongTypesTests(unittest.TestCase):
    def test_null_database_columns_do_not_crash(self):
        # Exam answers have wrong_reason=NULL until a single-question analysis ran.
        with patch.object(llm, "ask_json", return_value={"theories": [CARD]}) as ask:
            result = llm.analyze_wrong_types([group(wrong_reason=None, question=None, user_answer=None)])
        self.assertEqual(result[0]["title"], "제목")
        sample = json.loads(ask.call_args.args[1])["groups"][0]["sample_wrong_questions"][0]
        self.assertEqual(sample["wrong_reason"], "")
        self.assertEqual(sample["question"], "")

    def test_card_for_unselected_type_is_attached_to_selected_type(self):
        card = {**CARD, "category": "엉뚱한", "subcategory": "분류"}
        with patch.object(llm, "ask_json", return_value={"theories": [card]}):
            result = llm.analyze_wrong_types([group()])
        self.assertEqual((result[0]["category"], result[0]["subcategory"]), ("프로그래밍", "Java"))

    def test_list_fields_and_single_card_shapes_are_accepted(self):
        card = {**CARD, "memorization_tip": ["하나", "둘"], "summary": "요약"}
        with patch.object(llm, "ask_json", return_value=card):
            result = llm.analyze_wrong_types([group()])
        self.assertEqual(result[0]["memorization_tip"], "하나\n둘")

    def test_empty_model_answer_is_an_error_not_silent_success(self):
        with patch.object(llm, "ask_json", return_value={"theories": []}):
            with self.assertRaises(llm.ResponseFormatError):
                llm.analyze_wrong_types([group()])


class DroppedConnectionTests(unittest.TestCase):
    def setUp(self):
        for target in (patch.object(llm, "settings", return_value={"LLM_API_KEY": "test-key"}),
                       patch.object(llm.time, "sleep")):
            target.start()
            self.addCleanup(target.stop)
        self.opener = Mock()
        patcher = patch.object(llm.urllib.request, "build_opener", return_value=self.opener)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reset_and_incomplete_read_are_retried_then_reported_as_unavailable(self):
        for error in (ConnectionResetError("reset"), http.client.IncompleteRead(b"x"),
                      http.client.RemoteDisconnected("closed")):
            with self.subTest(error=type(error).__name__):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = error
                with self.assertRaises(llm.ServiceUnavailableError):
                    llm._request_json("코치", "자료")
                self.assertEqual(self.opener.open.call_count, 4)

    def test_connection_reset_recovers_on_retry(self):
        body = io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop",
                          "message": {"content": '{"ok": "예"}'}}]}).encode())
        self.opener.open.side_effect = [ConnectionResetError("reset"), body]
        self.assertEqual(llm._request_json("코치", "자료"), {"ok": "예"})


if __name__ == "__main__":
    unittest.main()
