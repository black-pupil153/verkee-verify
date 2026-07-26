"""质量评估模块测试"""

from verkeep_verify.monitor.quality import QualityTester


def test_number_check_extracts_value():
    qt = QualityTester()
    q = {"type": "number", "answer": "391"}
    assert qt._check_answer("It is 391.", q) is True
    assert qt._check_answer("大概是 391 左右", q) is True
    assert qt._check_answer("The result is 392", q) is False


def test_number_check_handles_thousands_separator():
    qt = QualityTester()
    q = {"type": "number", "answer": "1024"}
    assert qt._check_answer("It equals 1,024", q) is True


def test_token_match_exact():
    qt = QualityTester()
    q = {"type": "exact", "answer": "no"}
    assert qt._check_answer("No, we cannot.", q) is True
    # 不应把 'no' 匹配到 'nothing'
    assert qt._check_answer("nothing follows", q) is False


def test_contains_match():
    qt = QualityTester()
    q = {"type": "contains", "answer": "pacific"}
    assert qt._check_answer("The Pacific Ocean is largest.", q) is True


def test_code_pattern_match():
    qt = QualityTester()
    q = {
        "type": "code",
        "answer": "",
        "check_patterns": ["def is_palindrome", "return", "[::-1] or reversed"],
    }
    resp = "def is_palindrome(s):\n    return s == s[::-1]"
    assert qt._check_answer(resp, q) is True


def test_baseline_prefers_specific_key():
    qt = QualityTester()
    # glm-4.6 应命中 glm-4.6 而非 glm-4
    baseline = qt._get_baseline("glm-4.6")
    assert baseline == qt.BASELINES["glm-4.6"]


def test_baseline_default_for_unknown():
    qt = QualityTester()
    baseline = qt._get_baseline("totally-unknown-model")
    assert baseline["overall"] == 80


def test_run_test_with_mock_client():
    qt = QualityTester()

    def perfect_client(prompt):
        # 返回一个包含常见正确答案的响应，命中部分题目
        return "391 12 13 60 no 42 c 9 h2o mars shakespeare pacific 1789 北京 100"

    result = qt.run_test(client_factory=perfect_client, model="gpt-4", num_questions=8)
    assert "score" in result
    assert result["total"] > 0
    assert 0 <= result["score"] <= 100


def test_question_bank_size():
    qt = QualityTester()
    total = sum(len(v) for v in qt.TEST_QUESTIONS.values())
    # 当前题库约 37 题（math/logic/code/knowledge），远超原 18 题
    assert total >= 35
