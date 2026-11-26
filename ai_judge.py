"""
AI Similarity Engine for Devil's Plan 3 'Hidden Word' Turn-Based Team Game.
Evaluates similarity between [정답 단어 (출제자의 히든 단어)] and [제시한 단어/힌트]
in the exact format:
- 정답 여부: (일치 / 불일치)
- 유사도: (0~100점 사이 정수)
"""

import os
import re
import random
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


JUDGE_SYSTEM_PROMPT = """너는 《데블스 플랜 3》 '히든 워드' 게임의 유사도 채점 심판이야.
내가 [정답 단어]와 [플레이어가 제시한 단어/힌트]를 입력하면 다음 형식으로만 간결하게 답해 줘.

- 정답 여부: (일치 / 불일치)
- 유사도: (0~100점 사이 정수)"""


SETTER_HELPER_PROMPT = """너는 《데블스 플랜 3》 '히든 워드' 게임의 출제자 도우미 AI야.
출제자의 [히든 단어]와 의미적으로 매우 가까워서 유사도 채점 시 90~98점이 나올 만한 핵심 연상 단어(동의어, 같은 범주의 가장 가까운 단어, 핵심 특징 단어) 3개를 쉼표(,)로만 구분해서 출력해 줘.
절대 [히든 단어] 자체를 그대로 포함하지 마."""


# Rich Korean word bank with semantic clusters (including 90+ similarity words and lower similarity words)
WORD_BANK: List[Dict] = [
    {
        "word": "모래시계",
        "category": "사물",
        "semantic_map": {
            "해시계": 93, "물시계": 94, "초시계": 91, "스톱워치": 90, "타이머": 92,
            "시계": 88, "손목시계": 84, "괘종시계": 83, "자명종": 80, "모래": 85,
            "시간": 78, "알람": 72, "사막": 68, "유리병": 64, "유리": 62, "해변": 60, "중력": 58
        }
    },
    {
        "word": "블랙홀",
        "category": "우주/과학",
        "semantic_map": {
            "웜홀": 95, "화이트홀": 96, "사건의지평선": 93, "초신성": 91, "인터스텔라": 90,
            "암흑물질": 87, "중력": 85, "시공간": 84, "상대성이론": 82, "은하": 78,
            "우주": 76, "항성": 74, "구멍": 72, "행성": 70, "별": 68, "빛": 64
        }
    },
    {
        "word": "나침반",
        "category": "발명품/탐험",
        "semantic_map": {
            "나침의": 96, "동서남북": 92, "방위표": 93, "네비게이션": 90, "지도": 91,
            "방위": 87, "GPS": 86, "자석": 85, "북쪽": 84, "자기장": 84, "방향": 83,
            "길찾기": 82, "항해": 79, "탐험": 77, "바늘": 72, "등산": 68, "배": 65
        }
    },
    {
        "word": "신기루",
        "category": "자연/비유",
        "semantic_map": {
            "허상": 95, "착시": 93, "환상": 92, "아지랑이": 91, "오아시스": 90,
            "환각": 89, "사막": 82, "굴절": 80, "무지개": 78, "꿈": 75, "안개": 68
        }
    },
    {
        "word": "트로이목마",
        "category": "역사/IT",
        "semantic_map": {
            "목마": 94, "트로이": 93, "악성코드": 92, "컴퓨터바이러스": 91, "백도어": 90,
            "스파이웨어": 88, "바이러스": 87, "오디세우스": 85, "랜섬웨어": 84, "함정": 83,
            "위장": 82, "스파이": 80, "해킹": 80, "그리스신화": 78, "전쟁": 70
        }
    },
    {
        "word": "도플갱어",
        "category": "미스터리",
        "semantic_map": {
            "분신": 94, "닮은꼴": 93, "복제인간": 92, "클론": 91, "쌍둥이": 90,
            "아바타": 86, "데자뷰": 83, "평행이론": 81, "붕어빵": 80, "거울": 78, "그림자": 76
        }
    },
    {
        "word": "평행우주",
        "category": "SF/과학",
        "semantic_map": {
            "다중우주": 97, "멀티버스": 96, "평행세계": 95, "다른차원": 91, "시공간": 90,
            "차원": 86, "웜홀": 84, "양자역학": 83, "우주": 82, "시간여행": 81, "타임머신": 79
        }
    },
    {
        "word": "체스",
        "category": "보드게임",
        "semantic_map": {
            "체크메이트": 95, "장기": 93, "체커": 91, "바둑": 90, "보드게임": 88,
            "킹": 85, "퀸": 85, "나이트": 84, "비숍": 83, "룩": 82, "오목": 81, "전략": 75
        }
    },
    {
        "word": "북극성",
        "category": "천문",
        "semantic_map": {
            "북두칠성": 94, "작은곰자리": 92, "샛별": 91, "길잡이별": 93, "시리우스": 90,
            "큰곰자리": 87, "별자리": 86, "항성": 86, "나침반": 85, "별": 84, "이정표": 83
        }
    },
    {
        "word": "나비효과",
        "category": "과학/용어",
        "semantic_map": {
            "도미노효과": 94, "카오스이론": 92, "연쇄반응": 91, "스노우볼": 90,
            "도미노": 88, "날갯짓": 85, "플라시보효과": 84, "나비": 83, "인과관계": 82
        }
    },
    {
        "word": "김치찌개",
        "category": "음식",
        "semantic_map": {
            "된장찌개": 94, "부대찌개": 95, "순두부찌개": 93, "김치찜": 96, "김치국": 92,
            "찌개": 90, "김치": 87, "제육볶음": 83, "삼겹살": 82, "두부": 78, "공기밥": 76, "한식": 74
        }
    },
    {
        "word": "아메리카노",
        "category": "음료/카페",
        "semantic_map": {
            "에스프레소": 95, "아이스아메리카노": 97, "아아": 96, "카페라떼": 93, "콜드브루": 94,
            "커피": 91, "카페인": 86, "스타벅스": 84, "카페": 83, "원두": 82, "바리스타": 79
        }
    },
    {
        "word": "붕어빵",
        "category": "간식",
        "semantic_map": {
            "잉어빵": 97, "국화빵": 94, "호두과자": 91, "호떡": 92, "군고구마": 90,
            "팥": 86, "슈크림": 85, "겨울간식": 88, "포장마차": 80, "빵": 75, "겨울": 72
        }
    },
    {
        "word": "롤러코스터",
        "category": "놀이공원",
        "semantic_map": {
            "청룡열차": 96, "자이로드롭": 93, "바이킹": 92, "놀이기구": 91, "티익스프레스": 95,
            "놀이공원": 88, "에버랜드": 85, "롯데월드": 85, "회전목마": 83, "대관람차": 82, "스릴": 78
        }
    },
    {
        "word": "타임머신",
        "category": "SF/발명품",
        "semantic_map": {
            "시간여행": 95, "타임슬립": 93, "백투더퓨처": 92, "과거여행": 91, "미래여행": 90,
            "시공간": 86, "웜홀": 84, "과거": 80, "미래": 80, "시계": 76, "발명품": 70
        }
    },
    {
        "word": "카멜레온",
        "category": "동물",
        "semantic_map": {
            "도마뱀": 93, "이구아나": 92, "보호색": 95, "위장술": 91, "변신": 90,
            "파충류": 88, "개구리": 80, "거북이": 76, "색깔": 75, "동물": 65
        }
    },
]


def normalize_word(w: str) -> str:
    """Remove whitespace and punctuation for comparison."""
    return re.sub(r"[\s\-_.,!?\"'()\[\]]+", "", (w or "").strip()).lower()


class AIJudge:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.client = None
        self._init_client()

    def _init_client(self):
        if GENAI_AVAILABLE and self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                print(f"[AIJudge] Failed to initialize Gemini client: {e}")
                self.client = None
        else:
            self.client = None

    def set_api_key(self, api_key: str) -> bool:
        self.api_key = api_key.strip()
        self._init_client()
        return self.is_live_ai()

    def is_live_ai(self) -> bool:
        return self.client is not None

    def get_word_suggestions(self, count: int = 6) -> List[Dict]:
        """Returns random candidate words for players to pick as their secret word."""
        samples = random.sample(WORD_BANK, min(count, len(WORD_BANK)))
        return [{"word": s["word"], "category": s["category"]} for s in samples]

    def get_setter_90_plus_guide(self, target_word: str) -> List[str]:
        """
        Returns 3~4 candidate hint words that score >= 90 similarity for the setter's reference,
        so the setter never gets stuck if they can't think of a 90+ similarity word.
        """
        t_clean = normalize_word(target_word)
        entry = next((item for item in WORD_BANK if normalize_word(item["word"]) == t_clean), None)
        if entry:
            high_words = [
                k for k, v in sorted(entry["semantic_map"].items(), key=lambda x: -x[1])
                if 90 <= v < 100
            ]
            if high_words:
                return high_words[:5]

        # Try Gemini if available
        if self.is_live_ai():
            try:
                config = types.GenerateContentConfig(
                    system_instruction=SETTER_HELPER_PROMPT,
                    temperature=0.4,
                )
                response = self.client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=f"[히든 단어]: {target_word}",
                    config=config,
                )
                text = (response.text or "").strip()
                items = [x.strip() for x in text.split(",") if x.strip() and normalize_word(x) != t_clean]
                if items:
                    return items[:4]
            except Exception:
                pass

        # Fallback guide for custom words: partial roots or chosung hint
        suggestions = []
        if len(target_word) >= 2:
            suggestions.append(f"{target_word[:-1]}O")
            suggestions.append(f"O{target_word[1:]}")
        suggestions.append(f"초성 {self._extract_chosung(target_word)}")
        return suggestions

    def evaluate_similarity(self, target_word: str, player_word: str, attempt_count: int = 0) -> Dict:
        """
        Evaluates similarity between [정답 단어] and [플레이어가 제시한 단어/힌트].
        Always returns the exact required format in `formatted_response`:
        - 정답 여부: (일치 / 불일치)
        - 유사도: (0~100점 사이 정수)
        """
        target_clean = normalize_word(target_word)
        guess_clean = normalize_word(player_word)

        # 1. Exact match check (100% deterministic)
        if target_clean == guess_clean and target_clean != "":
            formatted = "- 정답 여부: 일치\n- 유사도: 100"
            return {
                "is_correct": True,
                "match_text": "일치",
                "similarity": 100,
                "formatted_response": formatted,
                "source": "exact"
            }

        # 2. Check curated semantic map first (guarantees 90+ for suggested guide words too!)
        entry = next((item for item in WORD_BANK if normalize_word(item["word"]) == target_clean), None)
        if entry:
            normalized_map = {normalize_word(k): v for k, v in entry.get("semantic_map", {}).items()}
            if guess_clean in normalized_map:
                score = normalized_map[guess_clean]
                return {
                    "is_correct": False,
                    "match_text": "불일치",
                    "similarity": score,
                    "formatted_response": f"- 정답 여부: 불일치\n- 유사도: {score}",
                    "source": "semantic_dict"
                }

        # 3. Try Live Gemini AI Judge if configured
        if self.is_live_ai():
            ai_res = self._call_gemini_judge(target_word, player_word)
            if ai_res is not None:
                return ai_res

        # 4. Built-in Semantic Judge Fallback
        score = self._calculate_fallback_similarity(target_word, player_word, attempt_count=attempt_count)
        is_correct = (score == 100)
        match_text = "일치" if is_correct else "불일치"
        formatted = f"- 정답 여부: {match_text}\n- 유사도: {score}"
        return {
            "is_correct": is_correct,
            "match_text": match_text,
            "similarity": score,
            "formatted_response": formatted,
            "source": "builtin_ai"
        }

    def _call_gemini_judge(self, target_word: str, player_word: str) -> Optional[Dict]:
        user_input = f"[정답 단어]: {target_word}\n[플레이어가 제시한 단어/힌트]: {player_word}"
        try:
            config = types.GenerateContentConfig(
                system_instruction=JUDGE_SYSTEM_PROMPT,
                temperature=0.1,
            )
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_input,
                config=config,
            )
            raw_text = (response.text or "").strip()
            parsed = self.parse_judge_output(raw_text, target_word, player_word)
            if parsed:
                parsed["source"] = "gemini"
                return parsed
        except Exception as e:
            print(f"[AIJudge] Gemini judge call error: {e}")
        return None

    @staticmethod
    def parse_judge_output(raw_text: str, target_word: str, player_word: str) -> Optional[Dict]:
        if not raw_text:
            return None

        if normalize_word(target_word) == normalize_word(player_word):
            is_correct = True
        else:
            is_correct = False

        sim_match = re.search(r"유사도\s*:\s*(\d{1,3})", raw_text)
        if not sim_match:
            nums = re.findall(r"\b(\d{1,3})\b", raw_text)
            if not nums:
                return None
            score = int(nums[-1])
        else:
            score = int(sim_match.group(1))

        score = max(0, min(100, score))
        if is_correct:
            score = 100
        elif score == 100:
            score = 99

        match_text = "일치" if is_correct else "불일치"
        formatted = f"- 정답 여부: {match_text}\n- 유사도: {score}"
        return {
            "is_correct": is_correct,
            "match_text": match_text,
            "similarity": score,
            "formatted_response": formatted,
        }

    def _calculate_fallback_similarity(self, target_word: str, player_word: str, attempt_count: int = 0) -> int:
        t_clean = normalize_word(target_word)
        p_clean = normalize_word(player_word)
        if not p_clean:
            return 0
        if t_clean == p_clean:
            return 100

        # Check chosung hint match (e.g., "초성 ㅁㄹㅅㄱ" or "ㅁㄹㅅㄱ")
        chosung = self._extract_chosung(target_word)
        if chosung and chosung in p_clean:
            return 92

        # Check masked character match (e.g., "모래시O" or "O래시계")
        common_chars = set(t_clean) & set(p_clean)
        if len(t_clean) >= 2 and len(common_chars) >= len(set(t_clean)) - 1:
            return 94

        # Check curated semantic map substring matches
        entry = next((item for item in WORD_BANK if normalize_word(item["word"]) == t_clean), None)
        if entry:
            sem_map = entry.get("semantic_map", {})
            normalized_map = {normalize_word(k): v for k, v in sem_map.items()}
            if p_clean in normalized_map:
                return normalized_map[p_clean]
            best_sub_score = 0
            for k_clean, v in normalized_map.items():
                if k_clean in p_clean or p_clean in k_clean:
                    best_sub_score = max(best_sub_score, min(95, max(50, v - 3)))
            if best_sub_score > 0:
                return best_sub_score

        # Substring overlap with target_word
        if t_clean in p_clean or p_clean in t_clean:
            overlap_ratio = min(len(t_clean), len(p_clean)) / max(len(t_clean), len(p_clean))
            return min(95, int(82 + overlap_ratio * 13))

        # Character / syllable overlap
        if common_chars:
            ratio = len(common_chars) / max(len(set(t_clean)), len(set(p_clean)))
            return min(91, int(55 + ratio * 38))

        # Jamo overlap (initial consonant similarity)
        t_cho = set(self._extract_chosung(t_clean))
        p_cho = set(self._extract_chosung(p_clean))
        cho_overlap = len(t_cho & p_cho)
        if cho_overlap > 0:
            base = 42 + int((cho_overlap / max(len(t_cho), 1)) * 35)
            # If setter is giving multiple hints on a custom word offline, gradually boost score
            boost = min(22, attempt_count * 6)
            return min(93, base + boost)

        pair_hash = sum(ord(c) * (i + 1) for i, c in enumerate(t_clean + ":" + p_clean))
        base_score = 25 + (pair_hash % 45)
        boost = min(25, attempt_count * 7)
        return min(92, base_score + boost)

    @staticmethod
    def _extract_chosung(word: str) -> str:
        CHOSUNG_LIST = [
            'ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ',
            'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ'
        ]
        result = []
        for char in word:
            if '가' <= char <= '힣':
                code = ord(char) - ord('가')
                cho_idx = code // 588
                result.append(CHOSUNG_LIST[cho_idx])
            else:
                result.append(char)
        return "".join(result)
