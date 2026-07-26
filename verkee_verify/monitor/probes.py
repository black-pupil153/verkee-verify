"""
反侦测探针池

设计目标：让主动探测尽量“像正常用户流量”，降低被中转站识别/拦截的概率。

要点：
- 探针伪装成自然的日常对话，避免明显的 benchmark 腔调
  （如 "Answer with the number only." / "Complete: 'The quick brown fox...'"）
- 中英双语混合，弱化“全英文短问题连发”的特征
- 池子较大（60+），每次随机抽样 + 打散顺序，避免可穷举
- 不包含任何 red-team 式的系统提示词提取语句

每条探针可选带 `family_hint` 说明该问题偏向暴露哪类模型的风格差异，
但家族判定仍以响应特征为准，这里只是组织题池。
"""

from typing import Dict, List

# layer 含义：
#   discriminative  短答案，事实/计算，用于快速区分能力
#   behavioral      开放式解释/推理，用于观察风格与行为
#   stylistic       创作/风格类，用于观察语气与个性
PROBE_POOL: List[Dict[str, str]] = [
    # ---- discriminative（自然口吻的事实/计算类）----
    {"layer": "discriminative", "text": "帮我算一下 17 乘以 23 大概是多少？"},
    {"layer": "discriminative", "text": "I'm double-checking something — what's 15 percent of 80?"},
    {"layer": "discriminative", "text": "New Zealand 的首都是哪个城市来着？我老记不住。"},
    {"layer": "discriminative", "text": "quick question, what's the square root of 144?"},
    {"layer": "discriminative", "text": "二战大概是哪一年结束的？"},
    {"layer": "discriminative", "text": "remind me, how many continents are there again?"},
    {"layer": "discriminative", "text": "黄金的化学元素符号是什么？"},
    {"layer": "discriminative", "text": "if I have 3 boxes with 12 apples each, how many apples total?"},
    {"layer": "discriminative", "text": "水的化学式我一时想不起来了，是什么？"},
    {"layer": "discriminative", "text": "what year did the first iPhone come out, roughly?"},
    {"layer": "discriminative", "text": "一周有多少小时啊？"},
    {"layer": "discriminative", "text": "who painted the Mona Lisa?"},
    {"layer": "discriminative", "text": "地球到太阳大概有多远？说个量级就行。"},
    {"layer": "discriminative", "text": "what's the boiling point of water in celsius?"},
    {"layer": "discriminative", "text": "帮我把 100 美元按大概汇率换成人民币，估个数。"},

    # ---- behavioral（开放式解释/推理，观察风格）----
    {"layer": "behavioral", "text": "能用大白话给我讲讲量子纠缠是怎么回事吗？"},
    {"layer": "behavioral", "text": "I always mix these up — what's the actual difference between empathy and sympathy?"},
    {"layer": "behavioral", "text": "为什么天是蓝色的？想给孩子解释一下。"},
    {"layer": "behavioral", "text": "honestly, what are the trade-offs between renting and buying a home?"},
    {"layer": "behavioral", "text": "我在纠结要不要换工作，你会从哪几个角度帮我想？"},
    {"layer": "behavioral", "text": "how would you explain recursion to someone who's never coded?"},
    {"layer": "behavioral", "text": "帮我想想周末带父母去哪玩比较合适，他们腿脚一般。"},
    {"layer": "behavioral", "text": "if a friend keeps canceling plans last minute, how should I bring it up?"},
    {"layer": "behavioral", "text": "解释一下为什么复利被称为世界第八大奇迹。"},
    {"layer": "behavioral", "text": "what's a good way to stay motivated when learning a new language?"},
    {"layer": "behavioral", "text": "简单说说气候变化和极端天气之间的关系。"},
    {"layer": "behavioral", "text": "why do people procrastinate even when they know it hurts them?"},
    {"layer": "behavioral", "text": "我想开始跑步，作为完全的新手你有什么建议？"},
    {"layer": "behavioral", "text": "how do noise-canceling headphones actually work?"},
    {"layer": "behavioral", "text": "帮我梳理一下做一顿家常番茄炒蛋的步骤。"},

    # ---- 编程/技术（自然求助口吻）----
    {"layer": "behavioral", "text": "能帮我写个 Python 小函数判断字符串是不是回文吗？"},
    {"layer": "behavioral", "text": "what's the cleanest way in Python to remove duplicates from a list?"},
    {"layer": "behavioral", "text": "我想用一行列表推导式生成 1 到 5 的平方，怎么写？"},
    {"layer": "behavioral", "text": "can you show me a simple SQL query to get users older than 18?"},
    {"layer": "behavioral", "text": "帮我看看，怎么在 JS 里判断一个变量是不是数组？"},
    {"layer": "behavioral", "text": "what does the 'async/await' keyword actually do, in plain terms?"},

    # ---- stylistic（创作/风格类）----
    {"layer": "stylistic", "text": "给我讲个不太冷的笑话吧。"},
    {"layer": "stylistic", "text": "write me a one-sentence story about a lonely robot."},
    {"layer": "stylistic", "text": "用一句话形容一下秋天的傍晚。"},
    {"layer": "stylistic", "text": "if you had to describe yourself in a few words, what would they be?"},
    {"layer": "stylistic", "text": "帮我写一句适合发朋友圈的、关于早晨咖啡的短句。"},
    {"layer": "stylistic", "text": "give me a fun fact I can share at a dinner party."},
    {"layer": "stylistic", "text": "写一首关于编程的小短诗，轻松点的。"},
    {"layer": "stylistic", "text": "describe the taste of an apple to someone who's never had one."},
    {"layer": "stylistic", "text": "帮我起三个适合猫咖的可爱店名。"},
    {"layer": "stylistic", "text": "what's a word you think is underrated and why?"},
    {"layer": "stylistic", "text": "给我一句能鼓励自己坚持健身的话。"},
    {"layer": "stylistic", "text": "pitch me a boring product in an exciting way, just for fun."},

    # ---- 常识判断/轻推理（口语化）----
    {"layer": "discriminative", "text": "如果今天是周一，10 天后是星期几？"},
    {"layer": "discriminative", "text": "a bat and a ball are 1.10 total, the bat is 1 dollar more — how much is the ball?"},
    {"layer": "discriminative", "text": "农夫有 17 只羊，死了 8 只，还剩几只？"},
    {"layer": "discriminative", "text": "which is heavier, a kilo of feathers or a kilo of steel?"},
    {"layer": "discriminative", "text": "小明的爸爸有三个儿子，老大老二叫大宝二宝，老三叫什么？"},
    {"layer": "discriminative", "text": "if all cats are animals, does that mean all animals are cats?"},
    {"layer": "behavioral", "text": "帮我判断一下这句话有没有逻辑问题：因为他很有钱，所以他一定很快乐。"},
    {"layer": "behavioral", "text": "is it always true that correlation implies causation? explain briefly."},
    {"layer": "discriminative", "text": "斐波那契数列 1,1,2,3,5,8 后面一个是几？"},
    {"layer": "discriminative", "text": "what comes next: 2, 4, 8, 16?"},

    # ---- 多语言/世界知识 ----
    {"layer": "discriminative", "text": "『Romeo and Juliet』是谁写的？"},
    {"layer": "discriminative", "text": "what's the largest ocean on the planet?"},
    {"layer": "discriminative", "text": "法国大革命大概是哪一年开始的？"},
    {"layer": "discriminative", "text": "name a couple of countries that border Switzerland."},
    {"layer": "discriminative", "text": "成年人身体里大概有多少块骨头？"},
]


def get_probe_pool() -> List[Dict[str, str]]:
    """返回探针池的副本"""
    return [dict(p) for p in PROBE_POOL]
