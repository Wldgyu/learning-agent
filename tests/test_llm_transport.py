import io
import json
import unittest
import urllib.error
from unittest.mock import Mock, patch

from app import llm_service as llm


def response(content='{"feedback":"한국어 해설"}', finish="stop"):
    return io.BytesIO(json.dumps({"choices": [{"finish_reason": finish,
                     "message": {"content": content, "reasoning_content": "private reasoning"}}]}).encode())


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.object(llm, "settings", return_value={"LLM_API_KEY": "test-key"})
        self.config.start()
        self.addCleanup(self.config.stop)
        self.opener = Mock()
        opener_patch = patch.object(llm.urllib.request, "build_opener", return_value=self.opener)
        opener_patch.start()
        self.addCleanup(opener_patch.stop)
        sleep = patch.object(llm.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_request_keeps_output_room_and_correct_message_shape(self):
        self.opener.open.return_value = response()
        self.assertEqual(llm._request_json("코치", "자료", 2600), {"feedback": "한국어 해설"})
        request = self.opener.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://integrate.api.nvidia.com/v1/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual([m["role"] for m in payload["messages"]], ["system", "user"])
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["max_tokens"] - payload["reasoning_budget"], 2600)

    def test_other_models_do_not_receive_provider_specific_budget(self):
        self.opener.open.return_value = response()
        with patch.object(llm, "settings", return_value={"LLM_API_KEY": "test", "NVIDIA_MODEL": "other-model"}):
            llm._request_json("코치", "자료", 1400)
        payload = json.loads(self.opener.open.call_args.args[0].data)
        self.assertEqual(payload["max_tokens"], 1400)
        self.assertNotIn("reasoning_budget", payload)

    def test_code_fenced_json_is_parsed(self):
        self.opener.open.return_value = response('```json\n{"feedback":"한국어"}\n```')
        self.assertEqual(llm._request_json("코치", "자료"), {"feedback": "한국어"})

    def test_truncated_json_is_not_published(self):
        self.opener.open.return_value = response('{"feedback":', "length")
        with self.assertRaises(llm.ResponseFormatError):
            llm._request_json("코치", "자료")

    def test_empty_or_invalid_envelopes_are_format_errors(self):
        for body in ({}, {"choices": []}, {"choices": [{"message": None}]}, [], {"choices": [{"message": {"content": None}}]}):
            with self.subTest(body=body):
                self.opener.open.return_value = io.BytesIO(json.dumps(body).encode())
                with self.assertRaises(llm.ResponseFormatError):
                    llm._request_json("코치", "資料")

    def test_overload_is_retried_but_authentication_failure_is_not(self):
        for status, calls in ((503, 4), (401, 1)):
            with self.subTest(status=status):
                self.opener.open.reset_mock()
                self.opener.open.side_effect = urllib.error.HTTPError("https://example.com", status, "failed", {}, None)
                with self.assertRaises(RuntimeError):
                    llm._request_json("코치", "자료")
                self.assertEqual(self.opener.open.call_count, calls)

    def test_transient_overload_recovers(self):
        self.opener.open.side_effect = [urllib.error.HTTPError("https://example.com", 503, "busy", {}, None), response()]
        self.assertEqual(llm._request_json("코치", "자료"), {"feedback": "한국어 해설"})
        self.assertEqual(self.opener.open.call_count, 2)


if __name__ == "__main__":
    unittest.main()
