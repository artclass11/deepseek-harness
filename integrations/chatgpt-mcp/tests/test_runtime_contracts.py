from __future__ import annotations

import unittest

from deepseek_harness_mcp.runtime import validate_question_answers, validate_task_prompt


class RuntimeContractTests(unittest.TestCase):
    def test_task_prompt_is_bounded(self) -> None:
        self.assertEqual(validate_task_prompt("  inspect the project  "), "inspect the project")
        with self.assertRaises(ValueError):
            validate_task_prompt(" ")
        with self.assertRaises(ValueError):
            validate_task_prompt("x" * 20001)

    def test_question_answers_require_exact_ids(self) -> None:
        questions = [{"id": "q1", "question": "Continue?"}, {"id": "q2", "question": "Which branch?"}]
        answer = {"answers": [{"id": "q1", "selected": ["Yes"]}, {"id": "q2", "selected": ["main"]}]}
        self.assertEqual(validate_question_answers(questions, answer["answers"]), answer)
        with self.assertRaises(ValueError):
            validate_question_answers(questions, [{"id": "q1", "selected": ["Yes"]}])
        with self.assertRaises(ValueError):
            validate_question_answers(questions, [
                {"id": "q1", "selected": ["Yes"]},
                {"id": "q1", "selected": ["Yes"]},
            ])


if __name__ == "__main__":
    unittest.main()
