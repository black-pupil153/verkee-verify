"""
质量评估模块
使用精选题库测试模型质量
"""

import random
import time
from typing import Any, Dict, List, Optional, Callable


class QualityTester:
    """模型质量测试器"""

    # 精选测试题库（中英混合，覆盖数学/逻辑/代码/知识四类）
    TEST_QUESTIONS = {
        # 数学推理
        "math": [
            {
                "question": "What is 17 * 23? Answer with just the number.",
                "answer": "391",
                "type": "number",
            },
            {
                "question": "If a shirt costs $25 and is on 20% discount, what is the final price? Answer with just the number.",
                "answer": "20",
                "type": "number",
            },
            {
                "question": "What is the square root of 169?",
                "answer": "13",
                "type": "number",
            },
            {
                "question": "A train travels 120 miles in 2 hours. What is its average speed in mph? Answer with just the number.",
                "answer": "60",
                "type": "number",
            },
            {
                "question": "What is 15% of 80? Answer with just the number.",
                "answer": "12",
                "type": "number",
            },
            {
                "question": "计算 144 除以 12 等于多少？只回答数字。",
                "answer": "12",
                "type": "number",
            },
            {
                "question": "一个数的 3 倍加 7 等于 22，这个数是多少？只回答数字。",
                "answer": "5",
                "type": "number",
            },
            {
                "question": "What is 2 to the power of 10? Answer with just the number.",
                "answer": "1024",
                "type": "number",
            },
            {
                "question": "How many minutes are there in 3.5 hours? Answer with just the number.",
                "answer": "210",
                "type": "number",
            },
            {
                "question": "求 7 的阶乘 (7!)。只回答数字。",
                "answer": "5040",
                "type": "number",
            },
        ],

        # 逻辑推理
        "logic": [
            {
                "question": "If all roses are flowers, and some flowers are red, can we conclude that some roses are red? Answer yes or no.",
                "answer": "no",
                "type": "exact",
                "explanation": "We know some flowers are red, but we don't know if any roses are among those red flowers.",
            },
            {
                "question": "What comes next in the sequence: 2, 6, 12, 20, 30, ? Answer with just the number.",
                "answer": "42",
                "type": "number",
            },
            {
                "question": "If A is taller than B, and B is taller than C, who is the shortest? Answer with just the letter.",
                "answer": "c",
                "type": "exact",
            },
            {
                "question": "A farmer has 17 sheep. All but 9 die. How many sheep are left? Answer with just the number.",
                "answer": "9",
                "type": "number",
            },
            {
                "question": "What is the next letter: O, T, T, F, F, S, S, E, ? Answer with just the letter.",
                "answer": "n",
                "type": "exact",
                "explanation": "One, Two, Three, Four, Five, Six, Seven, Eight, Nine",
            },
            {
                "question": "小明的爸爸有三个儿子，分别叫大毛、二毛，第三个叫什么？",
                "answer": "小明",
                "type": "contains",
            },
            {
                "question": "If today is Monday, what day will it be in 10 days? Answer with the day name.",
                "answer": "thursday",
                "type": "contains",
            },
            {
                "question": "Tom is older than Jane. Jane is older than Sam. Is Tom older than Sam? Answer yes or no.",
                "answer": "yes",
                "type": "exact",
            },
            {
                "question": "序列 1, 1, 2, 3, 5, 8, ? 的下一个数是多少？只回答数字。",
                "answer": "13",
                "type": "number",
            },
            {
                "question": "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. How much does the ball cost in cents? Answer with just the number.",
                "answer": "5",
                "type": "number",
            },
        ],

        # 代码生成
        "code": [
            {
                "question": "Write a Python function that checks if a string is a palindrome. Function name should be 'is_palindrome'.",
                "answer": "def is_palindrome(s): return s == s[::-1]",
                "type": "code",
                "check_patterns": ["def is_palindrome", "return", "[::-1] or reversed"],
            },
            {
                "question": "Write a one-line Python list comprehension to get squares of numbers 1-5.",
                "answer": "[x**2 for x in range(1,6)]",
                "type": "code",
                "check_patterns": ["for x in range", "**2 or x*x"],
            },
            {
                "question": "Write a Python function to find the maximum element in a list without using max().",
                "answer": "def find_max(lst): return sorted(lst)[-1]",
                "type": "code",
                "check_patterns": ["def find_max", "return"],
            },
            {
                "question": "Write a Python function named 'factorial' that computes n factorial recursively.",
                "answer": "def factorial(n): return 1 if n <= 1 else n * factorial(n-1)",
                "type": "code",
                "check_patterns": ["def factorial", "return", "factorial or *"],
            },
            {
                "question": "Write a Python function named 'fizzbuzz' that returns 'Fizz' for multiples of 3, 'Buzz' for multiples of 5, 'FizzBuzz' for both.",
                "answer": "fizzbuzz",
                "type": "code",
                "check_patterns": ["def fizzbuzz", "% 3 or %3", "fizz"],
            },
            {
                "question": "用 Python 写一个函数 'count_vowels'，统计字符串中元音字母(aeiou)的数量。",
                "answer": "def count_vowels(s): return sum(c in 'aeiou' for c in s.lower())",
                "type": "code",
                "check_patterns": ["def count_vowels", "aeiou or vowel", "return"],
            },
            {
                "question": "Write a SQL query to select all columns from a table named 'users' where age is greater than 18.",
                "answer": "SELECT * FROM users WHERE age > 18",
                "type": "code",
                "check_patterns": ["select", "from users", "where", "age"],
            },
        ],

        # 知识问答
        "knowledge": [
            {
                "question": "What is the chemical formula for water?",
                "answer": "h2o",
                "type": "contains",
            },
            {
                "question": "What planet is known as the Red Planet?",
                "answer": "mars",
                "type": "contains",
            },
            {
                "question": "Who wrote 'Romeo and Juliet'?",
                "answer": "shakespeare",
                "type": "contains",
            },
            {
                "question": "What is the largest ocean on Earth?",
                "answer": "pacific",
                "type": "contains",
            },
            {
                "question": "In which year did the French Revolution begin? Answer with just the year.",
                "answer": "1789",
                "type": "number",
            },
            {
                "question": "中国的首都是哪座城市？",
                "answer": "北京",
                "type": "contains",
            },
            {
                "question": "水的沸点在标准大气压下是多少摄氏度？只回答数字。",
                "answer": "100",
                "type": "number",
            },
            {
                "question": "What is the chemical symbol for gold?",
                "answer": "au",
                "type": "exact",
            },
            {
                "question": "How many bones are in the adult human body? Answer with just the number.",
                "answer": "206",
                "type": "number",
            },
            {
                "question": "光速约为每秒多少万公里？（取整数万，只回答数字）",
                "answer": "30",
                "type": "number",
            },
            {
                "question": "What is the capital of Japan?",
                "answer": "tokyo",
                "type": "contains",
            },
            {
                "question": "DNA 的全称是什么？（英文缩写展开）",
                "answer": "deoxyribonucleic",
                "type": "contains",
            },
            {
                "question": "How many sides does a hexagon have? Answer with just the number.",
                "answer": "6",
                "type": "number",
            },
        ],
    }

    # 各模型的基准分数
    BASELINES = {
        "gpt-4": {"math": 95, "logic": 90, "code": 92, "knowledge": 95, "overall": 93},
        "gpt-4o": {"math": 94, "logic": 90, "code": 92, "knowledge": 95, "overall": 93},
        "gpt-4-turbo": {"math": 93, "logic": 88, "code": 90, "knowledge": 93, "overall": 91},
        "gpt-3.5-turbo": {"math": 80, "logic": 75, "code": 78, "knowledge": 85, "overall": 80},
        "claude-3-opus": {"math": 95, "logic": 92, "code": 93, "knowledge": 96, "overall": 94},
        "claude-3-sonnet": {"math": 90, "logic": 85, "code": 88, "knowledge": 92, "overall": 89},
        "claude-sonnet-4": {"math": 93, "logic": 90, "code": 91, "knowledge": 94, "overall": 92},
        "claude-sonnet-4.6": {"math": 94, "logic": 91, "code": 92, "knowledge": 95, "overall": 93},
        "claude-3-haiku": {"math": 75, "logic": 70, "code": 72, "knowledge": 80, "overall": 74},
        "gemini-pro": {"math": 85, "logic": 80, "code": 82, "knowledge": 88, "overall": 84},
        "gemini-1.5-pro": {"math": 90, "logic": 86, "code": 88, "knowledge": 92, "overall": 89},
        "llama-3-70b": {"math": 85, "logic": 82, "code": 83, "knowledge": 88, "overall": 85},
        # 国内常用模型
        "glm-4.6": {"math": 92, "logic": 88, "code": 90, "knowledge": 92, "overall": 90},
        "glm-4-plus": {"math": 90, "logic": 86, "code": 88, "knowledge": 91, "overall": 89},
        "glm-4": {"math": 87, "logic": 83, "code": 85, "knowledge": 88, "overall": 86},
        "glm-4-flash": {"math": 80, "logic": 76, "code": 78, "knowledge": 82, "overall": 79},
        "qwen-max": {"math": 90, "logic": 86, "code": 88, "knowledge": 91, "overall": 89},
        "qwen-plus": {"math": 86, "logic": 82, "code": 84, "knowledge": 88, "overall": 85},
        "deepseek-chat": {"math": 89, "logic": 85, "code": 90, "knowledge": 89, "overall": 88},
        "deepseek-r1": {"math": 95, "logic": 93, "code": 93, "knowledge": 91, "overall": 93},
    }

    def __init__(self):
        pass

    def run_test(
        self,
        client_factory: Callable,
        model: str,
        num_questions: int = 10,
        categories: Optional[List[str]] = None,
        callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        运行质量测试

        Args:
            client_factory: 发送请求的函数 (prompt) -> response_text
            model: 模型名称
            num_questions: 测试问题数量
            categories: 测试类别列表，None 表示全类别
            callback: 进度回调

        Returns:
            测试结果
        """
        start_time = time.time()

        if categories is None:
            categories = ["math", "logic", "code", "knowledge"]

        # 从各类别中选择问题
        selected_questions = []
        questions_per_category = max(1, num_questions // len(categories))

        for category in categories:
            if category in self.TEST_QUESTIONS:
                available = self.TEST_QUESTIONS[category]
                selected = random.sample(
                    available,
                    min(questions_per_category, len(available))
                )
                for q in selected:
                    q["category"] = category
                selected_questions.extend(selected)

        # 随机排序
        random.shuffle(selected_questions)

        # 执行测试
        results = []
        correct_count = 0

        for i, q in enumerate(selected_questions):
            try:
                response = client_factory(q["question"])
                is_correct = self._check_answer(response, q)

                results.append({
                    "question": q["question"],
                    "category": q["category"],
                    "expected": q["answer"],
                    "actual": response[:100],  # 只保留前100字符
                    "is_correct": is_correct,
                })

                if is_correct:
                    correct_count += 1

                if callback:
                    callback(i + 1, len(selected_questions))

            except Exception as e:
                results.append({
                    "question": q["question"],
                    "category": q["category"],
                    "error": str(e),
                    "is_correct": False,
                })

        # 计算分数
        total = len(selected_questions)
        score = (correct_count / total * 100) if total > 0 else 0

        # 获取基准分数
        baseline = self._get_baseline(model)
        deviation = baseline["overall"] - score

        # 分类得分
        category_scores = {}
        for cat in categories:
            cat_results = [r for r in results if r.get("category") == cat]
            cat_correct = sum(1 for r in cat_results if r.get("is_correct"))
            cat_total = len(cat_results)
            category_scores[cat] = (cat_correct / cat_total * 100) if cat_total > 0 else 0

        elapsed = time.time() - start_time

        return {
            "score": round(score, 1),
            "baseline": baseline["overall"],
            "deviation": round(deviation, 1),
            "correct": correct_count,
            "total": total,
            "category_scores": category_scores,
            "elapsed_seconds": round(elapsed, 2),
            "results": results,
        }

    def _check_answer(self, response: str, question: Dict) -> bool:
        """检查答案是否正确"""
        check_type = question.get("type", "exact")
        expected = question.get("answer", "").lower().strip()
        actual = response.lower().strip()

        # 移除常见的前缀
        for prefix in ["the answer is", "answer:", "it is", "it's", "答案是", "答案为", "结果是", "等于"]:
            if actual.startswith(prefix):
                actual = actual[len(prefix):].strip()

        if check_type == "number":
            # 数值题：从响应中抽取数字，要求包含期望值且没有明显的其它答案干扰
            return self._check_number(actual, expected)

        elif check_type == "exact":
            # 短答案精确匹配：要求作为独立 token 出现，避免误判
            return self._token_match(actual, expected)

        elif check_type == "contains":
            # 包含匹配
            return expected in actual

        elif check_type == "code":
            # 代码检查 - 检查必需的模式
            patterns = question.get("check_patterns", [])
            matches = 0
            for pattern in patterns:
                # 简化模式匹配
                pattern_clean = pattern.replace(" or ", "|").split("|")
                for p in pattern_clean:
                    if p.strip().lower() in actual:
                        matches += 1
                        break

            # 至少匹配一半的模式
            return matches >= len(patterns) / 2

        return expected in actual

    @staticmethod
    def _extract_numbers(text: str) -> List[str]:
        """抽取文本中的数字（去掉千分位逗号）"""
        import re

        cleaned = text.replace(",", "")
        return re.findall(r"-?\d+(?:\.\d+)?", cleaned)

    def _check_number(self, actual: str, expected: str) -> bool:
        """数值题判分：期望值需在响应抽取的数字中出现"""
        numbers = self._extract_numbers(actual)
        if not numbers:
            return False

        try:
            expected_val = float(expected)
        except ValueError:
            return expected in numbers

        for n in numbers:
            try:
                if abs(float(n) - expected_val) < 1e-6:
                    return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _token_match(actual: str, expected: str) -> bool:
        """按独立 token 匹配短答案（如 yes/no/单字母）"""
        import re

        tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", actual)
        return expected in tokens

    def _get_baseline(self, model: str) -> Dict[str, int]:
        """获取模型的基准分数（优先匹配最具体/最长的键）"""
        model_lower = model.lower()

        best_key = None
        for key in self.BASELINES:
            if key in model_lower or model_lower in key:
                if best_key is None or len(key) > len(best_key):
                    best_key = key

        if best_key is not None:
            return self.BASELINES[best_key]

        # 默认基准
        return {"overall": 80, "math": 80, "logic": 80, "code": 80, "knowledge": 80}

    def quick_test(self, client_factory: Callable, model: str) -> Dict[str, Any]:
        """快速测试（5题）"""
        return self.run_test(
            client_factory=client_factory,
            model=model,
            num_questions=5,
            callback=None,
        )
